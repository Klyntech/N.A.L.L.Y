"""Hook models — config and invocation types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, Literal, Optional


class HookEvent(StrEnum):
    PreToolUse = "PreToolUse"
    PostToolUse = "PostToolUse"
    PostToolUseFailure = "PostToolUseFailure"
    UserPromptSubmit = "UserPromptSubmit"
    Stop = "Stop"


@dataclass
class HookConfig:
    """One hook entry from hooks.json."""

    name: str
    event: HookEvent
    matcher: str  # tool name glob, e.g. "run_command", "file_ops", "mcp_*", "*"
    command: str  # shell command to execute (stdio JSON)
    timeout: float = 10.0
    description: str = ""

    # Optional: if matcher contains `(pattern)` use tool input match
    # e.g. matcher "run_command(git push *)" — stored as separate field
    tool_pattern: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "HookConfig":
        # Support both string and dict
        event = HookEvent(data.get("event", "PreToolUse"))
        matcher = data.get("matcher", "*")
        # Explicit tool_pattern key (preferred) or parenthetical matcher
        tool_pattern = data.get("tool_pattern") or data.get("toolPattern") or data.get("pattern")
        # Extract parenthetical pattern: "run_command(git push *)" -> matcher=run_command, pattern=git push *
        if tool_pattern is None and "(" in matcher and matcher.endswith(")"):
            try:
                idx = matcher.index("(")
                tool_pattern = matcher[idx + 1 : -1]
                matcher = matcher[:idx]
            except Exception:
                pass
        return cls(
            name=data.get("name", "unnamed"),
            event=event,
            matcher=matcher,
            command=data.get("command", ""),
            timeout=float(data.get("timeout", 10.0)),
            description=data.get("description", ""),
            tool_pattern=tool_pattern,
        )


@dataclass
class HookInvocation:
    """Data passed to hook via stdin JSON."""

    event: HookEvent
    tool_name: str
    tool_args: Dict[str, Any]
    tool_output: Optional[str] = None
    tool_success: Optional[bool] = None
    cwd: Optional[str] = None
    session_id: Optional[str] = None

    def to_json(self) -> dict:
        d = {
            "hook_event_name": self.event.value,
            "tool_name": self.tool_name,
            "tool_input": self.tool_args,
        }
        if self.tool_output is not None:
            d["tool_output"] = self.tool_output
            d["tool_success"] = self.tool_success
        if self.cwd:
            d["cwd"] = self.cwd
        if self.session_id:
            d["session_id"] = self.session_id
        return d


@dataclass
class HookResult:
    """Result parsed from hook stdout JSON."""

    # decision: allow | deny
    decision: Literal["allow", "deny"] = "allow"
    reason: Optional[str] = None
    # For PostToolUse: text appended to tool result and shown to LLM
    additionalContext: Optional[str] = None
    # For PreToolUse: mutated tool_input (future)
    tool_input: Optional[Dict[str, Any]] = None
    # Raw
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @classmethod
    def from_json(cls, data: dict, exit_code: int = 0, stdout: str = "", stderr: str = "", timed_out: bool = False) -> "HookResult":
        if not isinstance(data, dict):
            return cls(decision="allow", exit_code=exit_code, stdout=stdout, stderr=stderr, timed_out=timed_out)
        # Hook stdout may be {"hookSpecificOutput": {"permissionDecision": "deny", ...}} or direct
        payload = data.get("hookSpecificOutput", data)
        decision = payload.get("permissionDecision") or payload.get("decision") or "allow"
        if decision not in ("allow", "deny"):
            decision = "allow"
        return cls(
            decision=decision,  # type: ignore
            reason=payload.get("permissionDecisionReason") or payload.get("reason"),
            additionalContext=payload.get("additionalContext"),
            tool_input=payload.get("tool_input") or payload.get("toolInput"),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
        )

    @classmethod
    def passthrough(cls, exit_code: int = 0, stdout: str = "", stderr: str = "", timed_out: bool = False) -> "HookResult":
        return cls(decision="allow", exit_code=exit_code, stdout=stdout, stderr=stderr, timed_out=timed_out)
