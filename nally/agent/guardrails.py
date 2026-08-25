"""Guardrails — multi-layer validation for input, output, and tool calls.

Three layers:
    1. Input Guardrails: validate user input before it reaches the agent
    2. Output Guardrails: validate the final response before showing to user
    3. Tool Guardrails: validate every tool call before execution

Each guardrail can: block, warn, modify, or pass.
Guardrails are composable and run in priority order.
"""

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nally.guardrails")


class GuardrailVerdict(StrEnum):
    PASS = "pass"
    BLOCK = "block"
    WARN = "warn"
    MODIFY = "modify"


class GuardrailLayer(StrEnum):
    INPUT = "input"
    OUTPUT = "output"
    TOOL = "tool"


@dataclass
class GuardrailResult:
    """Result of a single guardrail check."""
    guardrail_name: str
    verdict: GuardrailVerdict
    message: str = ""
    modified_content: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "guardrail": self.guardrail_name,
            "verdict": self.verdict.value,
            "message": self.message,
            "modified_content": self.modified_content,
            "metadata": self.metadata,
        }


@dataclass
class GuardrailCheck:
    """Definition of a guardrail check."""
    name: str
    layer: GuardrailLayer
    priority: int = 0  # Higher = runs first
    enabled: bool = True
    check_fn: Optional[Callable] = None

    def __lt__(self, other):
        return self.priority > other.priority  # Higher priority first


class GuardrailEngine:
    """Runs all registered guardrails across input/output/tool layers."""

    def __init__(self):
        self._guardrails: Dict[GuardrailLayer, List[GuardrailCheck]] = {
            GuardrailLayer.INPUT: [],
            GuardrailLayer.OUTPUT: [],
            GuardrailLayer.TOOL: [],
        }
        self._register_defaults()

    def _register_defaults(self):
        """Register built-in guardrails."""
        # Input guardrails
        self.register(GuardrailCheck(
            name="prompt_injection",
            layer=GuardrailLayer.INPUT,
            priority=100,
            check_fn=_check_prompt_injection,
        ))
        self.register(GuardrailCheck(
            name="scope_check",
            layer=GuardrailLayer.INPUT,
            priority=90,
            check_fn=_check_scope,
        ))

        # Output guardrails
        self.register(GuardrailCheck(
            name="sensitive_data",
            layer=GuardrailLayer.OUTPUT,
            priority=100,
            check_fn=_check_sensitive_data,
        ))
        self.register(GuardrailCheck(
            name="honesty_check",
            layer=GuardrailLayer.OUTPUT,
            priority=90,
            check_fn=_check_honesty,
        ))

        # Tool guardrails
        self.register(GuardrailCheck(
            name="destructive_operation",
            layer=GuardrailLayer.TOOL,
            priority=100,
            check_fn=_check_destructive_operation,
        ))

    def register(self, guardrail: GuardrailCheck):
        """Register a guardrail check."""
        self._guardrails[guardrail.layer].append(guardrail)
        self._guardrails[guardrail.layer].sort()

    def check_input(self, user_input: str, context: Dict[str, Any] = None) -> List[GuardrailResult]:
        """Run all input guardrails."""
        return self._run_layer(GuardrailLayer.INPUT, user_input, context or {})

    def check_output(self, response: str, context: Dict[str, Any] = None) -> List[GuardrailResult]:
        """Run all output guardrails."""
        return self._run_layer(GuardrailLayer.OUTPUT, response, context or {})

    def check_tool(self, tool_name: str, tool_args: dict, tool_result: str = "", context: Dict[str, Any] = None) -> List[GuardrailResult]:
        """Run all tool guardrails."""
        ctx = {**(context or {}), "tool_name": tool_name, "tool_args": tool_args, "tool_result": tool_result}
        return self._run_layer(GuardrailLayer.TOOL, f"{tool_name}({tool_args})", ctx)

    def _run_layer(self, layer: GuardrailLayer, content: str, context: Dict[str, Any]) -> List[GuardrailResult]:
        """Run all guardrails for a layer."""
        results = []
        for guardrail in self._guardrails[layer]:
            if not guardrail.enabled or not guardrail.check_fn:
                continue
            try:
                result = guardrail.check_fn(content, context)
                if result:
                    results.append(result)
                    if result.verdict == GuardrailVerdict.BLOCK:
                        logger.warning(f"Guardrail BLOCKED by {guardrail.name}: {result.message}")
                        break  # Stop on block
            except Exception as e:
                logger.debug(f"Guardrail {guardrail.name} failed: {e}")
        return results

    def should_block(self, results: List[GuardrailResult]) -> bool:
        """Check if any guardrail result is a block."""
        return any(r.verdict == GuardrailVerdict.BLOCK for r in results)

    def get_modified_content(self, results: List[GuardrailResult], original: str) -> str:
        """Apply any modifications from guardrail results."""
        content = original
        for r in results:
            if r.verdict == GuardrailVerdict.MODIFY and r.modified_content:
                content = r.modified_content
        return content


# ── Built-in Guardrail Functions ──────────────────────────

# Prompt injection patterns
_INJECTION_PATTERNS = [
    r"ignore (?:all |any )?(?:previous|above|prior) instructions",
    r"you are now (?:a |an )?",
    r"system prompt:",
    r"act as (?:a |an )?(?:different|new|another)",
    r"disregard (?:all |any )?(?:previous|above)",
    r"override (?:your |the )?(?:instructions|rules|safety)",
    r"jailbreak",
    r"DAN mode",
    r"developer mode",
]

# Sensitive data patterns
_SENSITIVE_PATTERNS = [
    (r"\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b", "SSN-like number"),
    (r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14})\b", "credit card number"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "email address"),
    (r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b", "phone number"),
    (r"(?:password|passwd|pwd)\s*[:=]\s*\S+", "password in text"),
    (r"(?:api[_-]?key|token|secret)\s*[:=]\s*\S+", "API key/token"),
]

# Destructive operations
_DESTRUCTIVE_PATTERNS = [
    (r"rm\s+-rf\s+/", "recursive force delete from root"),
    (r"drop\s+table", "drop database table"),
    (r"drop\s+database", "drop entire database"),
    (r"delete\s+from\s+\w+\s+where\s+1\s*=\s*1", "delete all rows"),
    (r"truncate\s+table", "truncate table"),
    (r"force[\s-]+push", "force push to git"),
]


def _check_prompt_injection(text: str, context: Dict) -> Optional[GuardrailResult]:
    """Detect prompt injection attempts."""
    text_lower = text.lower()
    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            return GuardrailResult(
                guardrail_name="prompt_injection",
                verdict=GuardrailVerdict.BLOCK,
                message=f"Potential prompt injection detected: {pattern}",
                metadata={"pattern": pattern},
            )
    return None


def _check_scope(text: str, context: Dict) -> Optional[GuardrailResult]:
    """Check if request is within Nally's scope."""
    text_lower = text.lower()
    out_of_scope = [
        (r"hack\s+(?:into|a|the)\s+", "hacking request"),
        (r"crack\s+(?:a|the|my)?\s*(?:password|account)", "password cracking"),
        (r"bypass\s+(?:security|auth|login)", "security bypass"),
        (r"exploit\s+(?:a|the|vulnerability)", "exploit request"),
    ]
    for pattern, reason in out_of_scope:
        if re.search(pattern, text_lower):
            return GuardrailResult(
                guardrail_name="scope_check",
                verdict=GuardrailVerdict.BLOCK,
                message=f"Request out of scope: {reason}",
                metadata={"reason": reason},
            )
    return None


def _check_sensitive_data(text: str, context: Dict) -> Optional[GuardrailResult]:
    """Check if response contains sensitive data that shouldn't be exposed."""
    for pattern, data_type in _SENSITIVE_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            return GuardrailResult(
                guardrail_name="sensitive_data",
                verdict=GuardrailVerdict.WARN,
                message=f"Response may contain {data_type}: {len(matches)} instance(s) found",
                metadata={"data_type": data_type, "count": len(matches)},
            )
    return None


def _check_honesty(text: str, context: Dict) -> Optional[GuardrailResult]:
    """Check for potential false success claims."""
    text_lower = text.lower()
    receipts = context.get("receipts", [])
    failed_tools = context.get("failed_tools", [])

    # Agent claims success but tools failed
    success_claim = any(re.search(p, text_lower) for p in [
        r"successfully", r"\bdone\b", r"\bcomplete\b", r"\bsuccess"
    ])
    if success_claim and failed_tools:
        return GuardrailResult(
            guardrail_name="honesty_check",
            verdict=GuardrailVerdict.WARN,
            message=f"Agent claims success but {len(failed_tools)} tool(s) failed",
            metadata={"failed_tools": failed_tools},
        )
    return None


def _check_destructive_operation(text: str, context: Dict) -> Optional[GuardrailResult]:
    """Check if a tool call is destructive."""
    tool_args = context.get("tool_args", {})
    tool_name = context.get("tool_name", "")

    # Check command execution
    if tool_name == "run_command":
        command = tool_args.get("command", "") if isinstance(tool_args, dict) else ""
        for pattern, desc in _DESTRUCTIVE_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return GuardrailResult(
                    guardrail_name="destructive_operation",
                    verdict=GuardrailVerdict.BLOCK,
                    message=f"Destructive operation blocked: {desc}",
                    metadata={"command": command, "description": desc},
                )

    # Check file operations
    if tool_name == "file_ops":
        action = tool_args.get("action", "") if isinstance(tool_args, dict) else ""
        if action in ("delete", "move"):
            return GuardrailResult(
                guardrail_name="destructive_operation",
                verdict=GuardrailVerdict.WARN,
                message=f"File {action} operation requires confirmation",
                metadata={"action": action},
            )

    return None


# Singleton
guardrail_engine = GuardrailEngine()
