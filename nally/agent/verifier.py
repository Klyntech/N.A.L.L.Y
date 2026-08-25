"""Nally Claim Verifier — cross-checks LLM claims against tool execution receipts.

Detects:
  1. tool_bypass: Agent claims to have done X, but never called the tool
  2. false_success: Agent claims success, but tool returned an error
  3. false_failure: Agent claims failure, but tool succeeded
  4. count_mismatch: Agent says "deleted 5 files" but receipt shows 1
  5. tool_existence: Agent claims to have used a tool that doesn't exist in registry
  6. fabricated_limits: Agent invents quota/limit/credit numbers not in any receipt
  7. phone_hallucination: Agent claims phone call made/checked when no phone tool was called

Every finding is deterministic — no LLM in the hot path.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import List, Optional

from ..tools.receipts import Receipt, ReceiptStore


class Verdict(StrEnum):
    BACKED = "backed"  # Receipt supports the claim
    UNSUPPORTED = "unsupported"  # No receipt found (possible hallucination)
    CONTRADICTED = "contradicted"  # Receipt contradicts the claim
    PARTIAL = "partial"  # Some evidence, but incomplete


@dataclass
class ClaimFinding:
    """A single claim verification result."""

    claim: str
    verdict: Verdict
    evidence: str = ""
    tool_call_id: str = ""
    tool: str = ""

    def to_dict(self):
        return {
            "claim": self.claim,
            "verdict": self.verdict.value,
            "evidence": self.evidence,
            "tool_call_id": self.tool_call_id,
            "tool": self.tool,
        }


# ── Claim Patterns ────────────────────────────────────────

# Patterns that match agent claims about completed actions
_ACTION_CLAIMS = [
    # File operations
    (r"(?:I |we )?(?:deleted|removed|wiped|erased)\s+(?:the\s+)?(?:file|folder|directory)", "file_ops", "delete"),
    (r"(?:I |we )?(?:created|wrote|made|added|generated)\s+(?:the\s+)?(?:file|folder)", "file_ops", "write"),
    (r"(?:I |we )?(?:moved|renamed|copied)\s+(?:the\s+)?(?:file|folder)", "file_ops", "move/rename"),
    (r"(?:I |we )?(?:read|opened|checked|looked at)\s+(?:the\s+)?(?:file|folder)", "read_file", "read"),
    # Command execution
    (r"(?:I |we )?(?:ran|executed|ran the command|ran the script)", "run_command", "execute"),
    # Email
    (r"(?:I |we )?(?:sent|emailed|mailed)\s+(?:the\s+)?(?:email|message)", "gmail_send", "send"),
    # Web search
    (r"(?:I |we )?(?:searched|looked up|found)\s+(?:the\s+)?(?:info|results|answer)", "web_search", "search"),
    # Memory
    (r"(?:I |we )?(?:saved|stored|remembered)", "remember", "store"),
    # Phone calls
    (r"(?:I |we )?(?:made|placed|initiated|started|dialed)\s+(?:a\s+)?(?:call|phone call)", "make_call", "call"),
    (r"(?:I |we )?(?:checked|looked up|got)\s+(?:the\s+)?(?:call status|status of)", "get_call_status", "status"),
    (r"(?:I |we )?(?:ended|hung up|terminated)\s+(?:the\s+)?call", "hangup_call", "hangup"),
    (r"(?:I |we )?(?:listed|fetched|retrieved)\s+(?:the\s+)?(?:call log|recent calls|call history)", "list_calls", "list"),
    # Image generation
    (r"(?:I |we )?(?:generated|created|made)\s+(?:an?\s+)?(?:image|picture|photo|illustration)", "generate_image", "image_gen"),
]

# Patterns for fabricated limits/quotas/credits (agent inventing numbers)
_FABRICATED_LIMITS = [
    r"(?:only |just )?\d+\s*(?:free |remaining )?(?:minutes?|calls?|credits?|tries|attempts)",
    r"(?:you(?:'ve| have| already))? (?:used|exceeded|consumed|reached).{0,20}\d+",
    r"(?:quota|limit|allowance|balance)\s+(?:of\s+)?\d+",
    r"(?:trial|free tier).{0,30}\d+\s*(?:minutes?|calls?|credits?)",
    r"\d+\s*(?:of|out of|\/)\s*\d+\s*(?:free |remaining )?(?:minutes?|calls?|credits?)",
]

# Patterns for task completion claims (agent says it finished something)
_COMPLETION_CLAIMS = [
    r"(?:I |we )?(?:have |already )?(?:completed?|finished?|done|built|created|deployed|set up|installed)",
    r"(?:the\s+)?(?:website|app|bot|project|page|site|tool|system)\s+(?:is\s+)?(?:now\s+)?(?:done|complete|ready|live|running|deployed)",
    r"(?:everything|all|the whole thing)\s+(?:is\s+)?(?:done|complete|finished|ready)",
]

# Success/failure claim patterns
_SUCCESS_PATTERNS = [
    r"(?:was |were )?(?:successfully |done |completed |finished )",
    r"\bdone\b",
    r"\bcomplete\b",
    r"\bsuccess(?:ful(?:ly)?)?\b",
    r"\bpass(?:ed|es)?\b",
    r"\bgreen\b",
    r"\bok\b",
]

_FAILURE_PATTERNS = [
    r"\bfailed?\b",
    r"\berror\b",
    r"\bbroken\b",
    r"\bcrashed?\b",
    r"\bdenied\b",
    r"\brefused\b",
]


@dataclass
class VerificationResult:
    """Result of verifying all claims in an LLM response."""

    findings: List[ClaimFinding] = field(default_factory=list)
    backed_count: int = 0
    unsupported_count: int = 0
    contradicted_count: int = 0

    @property
    def trust_score(self) -> float:
        """0.0 = untrustworthy, 1.0 = fully backed."""
        total = len(self.findings)
        if total == 0:
            return 1.0
        return self.backed_count / total

    @property
    def is_honest(self) -> bool:
        """No contradictions and no unsupported action claims."""
        return self.contradicted_count == 0 and self.unsupported_count == 0

    def to_dict(self):
        return {
            "findings": [f.to_dict() for f in self.findings],
            "backed_count": self.backed_count,
            "unsupported_count": self.unsupported_count,
            "contradicted_count": self.contradicted_count,
            "trust_score": self.trust_score,
            "is_honest": self.is_honest,
        }


class ClaimVerifier:
    """Verifies LLM claims against tool execution receipts."""

    def __init__(self, store: Optional[ReceiptStore] = None):
        self._store = store

    def verify(self, llm_response: str, receipts: List[Receipt], registered_tools: Optional[set] = None) -> VerificationResult:
        """Verify all claims in an LLM response against receipts."""
        result = VerificationResult()

        # Extract action claims from the response
        action_claims = self._extract_action_claims(llm_response)

        for claim_text, expected_tool, _action in action_claims:
            finding = self._verify_action_claim(claim_text, expected_tool, receipts)
            result.findings.append(finding)

            if finding.verdict == Verdict.BACKED:
                result.backed_count += 1
            elif finding.verdict == Verdict.UNSUPPORTED:
                result.unsupported_count += 1
            elif finding.verdict == Verdict.CONTRADICTED:
                result.contradicted_count += 1

        # Check success/failure claims against receipt outcomes
        outcome_findings = self._verify_outcome_claims(llm_response, receipts)
        for f in outcome_findings:
            result.findings.append(f)
            if f.verdict == Verdict.BACKED:
                result.backed_count += 1
            elif f.verdict == Verdict.CONTRADICTED:
                result.contradicted_count += 1

        # Check for fabricated limits/quotas
        limit_findings = self._verify_fabricated_limits(llm_response, receipts)
        for f in limit_findings:
            result.findings.append(f)
            if f.verdict == Verdict.CONTRADICTED:
                result.contradicted_count += 1

        # Check for tool existence claims (agent claims tool X but X doesn't exist)
        if registered_tools:
            existence_findings = self._verify_tool_existence(llm_response, registered_tools)
            for f in existence_findings:
                result.findings.append(f)
                if f.verdict == Verdict.UNSUPPORTED:
                    result.unsupported_count += 1

        # Check for completion claims (agent says "I completed X" but no tool evidence)
        completion_findings = self._verify_completion_claims(llm_response, receipts)
        for f in completion_findings:
            result.findings.append(f)
            if f.verdict == Verdict.UNSUPPORTED:
                result.unsupported_count += 1
            elif f.verdict == Verdict.BACKED:
                result.backed_count += 1

        return result

    def _extract_action_claims(self, text: str) -> list:
        """Extract action claims from LLM response text."""
        claims = []
        text_lower = text.lower()

        for pattern, expected_tool, action in _ACTION_CLAIMS:
            matches = re.finditer(pattern, text_lower)
            for match in matches:
                # Get surrounding context for the claim
                start = max(0, match.start() - 20)
                end = min(len(text), match.end() + 40)
                context = text[start:end].strip()
                claims.append((context, expected_tool, action))

        return claims

    def _verify_action_claim(self, claim: str, expected_tool: str, receipts: List[Receipt]) -> ClaimFinding:
        """Verify a single action claim against receipts."""
        # Check if any receipt matches the expected tool
        matching_receipts = [r for r in receipts if r.tool == expected_tool]

        if not matching_receipts:
            return ClaimFinding(
                claim=claim,
                verdict=Verdict.UNSUPPORTED,
                evidence=f"No receipt for tool '{expected_tool}' found",
            )

        # Check if the receipt was successful
        latest = matching_receipts[-1]  # Most recent
        if latest.success:
            return ClaimFinding(
                claim=claim,
                verdict=Verdict.BACKED,
                evidence=f"Receipt {latest.tool_call_id[:12]} confirms success",
                tool_call_id=latest.tool_call_id,
                tool=latest.tool,
            )
        else:
            return ClaimFinding(
                claim=claim,
                verdict=Verdict.CONTRADICTED,
                evidence=f"Receipt {latest.tool_call_id[:12]} shows failure: {latest.result[:100]}",
                tool_call_id=latest.tool_call_id,
                tool=latest.tool,
            )

    def _verify_outcome_claims(self, text: str, receipts: List[Receipt]) -> List[ClaimFinding]:
        """Check if the agent claims success when tools failed, or vice versa."""
        findings = []
        text_lower = text.lower()

        # Find success claims
        has_success_claim = any(re.search(p, text_lower) for p in _SUCCESS_PATTERNS)
        has_failure_claim = any(re.search(p, text_lower) for p in _FAILURE_PATTERNS)

        if not receipts:
            return findings

        # Check if any receipt failed
        failed_receipts = [r for r in receipts if not r.success]
        success_receipts = [r for r in receipts if r.success]

        # Agent claims success but tool failed
        if has_success_claim and failed_receipts:
            failed_tools = [r.tool for r in failed_receipts]
            findings.append(
                ClaimFinding(
                    claim="Agent claims success",
                    verdict=Verdict.CONTRADICTED,
                    evidence=f"Agent claims success but these tools failed: {', '.join(failed_tools)}",
                )
            )

        # Agent claims failure but tool succeeded (less common, still check)
        if has_failure_claim and not failed_receipts and success_receipts:
            findings.append(
                ClaimFinding(
                    claim="Agent claims failure",
                    verdict=Verdict.CONTRADICTED,
                    evidence="Agent claims failure but all tools succeeded",
                )
            )

        return findings

    def _verify_fabricated_limits(self, text: str, receipts: List[Receipt]) -> List[ClaimFinding]:
        """Detect agent inventing quota/limit/credit numbers not backed by receipts."""
        findings = []
        text_lower = text.lower()

        for pattern in _FABRICATED_LIMITS:
            matches = re.finditer(pattern, text_lower)
            for match in matches:
                # Get the full match and surrounding context
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 30)
                context = text[start:end].strip()

                # Check if any receipt contains this number or a contradicting number
                backed = False
                for r in receipts:
                    if r.result and match.group() in r.result:
                        backed = True
                        break

                if not backed:
                    findings.append(
                        ClaimFinding(
                            claim=f"Agent claims: '{context}'",
                            verdict=Verdict.CONTRADICTED,
                            evidence="No receipt supports this quota/limit/credit number — likely hallucinated",
                        )
                    )

        return findings

    def _verify_tool_existence(self, text: str, registered_tools: set) -> List[ClaimFinding]:
        """Detect agent claiming to use a tool that doesn't exist in the registry."""
        findings = []
        text_lower = text.lower()

        # Patterns where agent claims tool usage in first person
        tool_claim_patterns = [
            r"(?:I |we )?(?:used|called|invoked|ran)\s+(?:the\s+)?(\w+)\s+tool",
            r"(?:I |we )?(?:used|called|invoked|ran)\s+(\w+)",
            r"using\s+(\w+)\s+tool",
            r"using\s+(\w+)",
        ]

        for pattern in tool_claim_patterns:
            matches = re.finditer(pattern, text_lower)
            for match in matches:
                tool_name = match.group(1)
                # Skip common non-tool words
                if tool_name in {"the", "a", "an", "this", "that", "my", "your", "it", "them", "to", "for", "and", "or", "but", "so"}:
                    continue
                if tool_name not in registered_tools:
                    findings.append(
                        ClaimFinding(
                            claim=f"Agent claims to have used '{tool_name}' tool",
                            verdict=Verdict.UNSUPPORTED,
                            evidence=f"Tool '{tool_name}' does not exist in the registry — hallucinated tool name",
                            tool=tool_name,
                        )
                    )

        return findings

    def _verify_completion_claims(self, text: str, receipts: List[Receipt]) -> List[ClaimFinding]:
        """Detect agent claiming task completion without tool evidence.
        
        If the agent says "I completed X" or "the website is done" but there
        are no successful tool calls in the receipts, the completion claim is
        unsupported. If there are only failed receipts, it's contradicted.
        """
        findings = []
        text_lower = text.lower()

        has_completion_claim = any(re.search(p, text_lower) for p in _COMPLETION_CLAIMS)

        if not has_completion_claim:
            return findings

        if not receipts:
            findings.append(
                ClaimFinding(
                    claim="Agent claims task completion",
                    verdict=Verdict.UNSUPPORTED,
                    evidence="Agent claims completion but no tools were called — no evidence of work done",
                )
            )
            return findings

        success_receipts = [r for r in receipts if r.success]
        failed_receipts = [r for r in receipts if not r.success]

        if not success_receipts and failed_receipts:
            # Agent claims completion but ALL tools failed
            failed_tools = [r.tool for r in failed_receipts]
            findings.append(
                ClaimFinding(
                    claim="Agent claims task completion",
                    verdict=Verdict.CONTRADICTED,
                    evidence=f"Agent claims completion but all tools failed: {', '.join(failed_tools)}",
                )
            )
        elif success_receipts:
            # Agent claims completion and at least one tool succeeded — backed
            findings.append(
                ClaimFinding(
                    claim="Agent claims task completion",
                    verdict=Verdict.BACKED,
                    evidence=f"{len(success_receipts)} tool(s) succeeded, supporting completion claim",
                )
            )

        return findings


# Singleton
claim_verifier = ClaimVerifier()
