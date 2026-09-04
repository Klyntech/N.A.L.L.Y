"""Structured tool execution contract.

Boring by design: one reliable boundary between tool implementations and
callers. Receipts, permissions, retries, and verification stay separate.

Legacy tools that return ``str`` are adapted via ``ToolResult.from_legacy``.
Tools may return ``ToolResult`` directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass
class ToolResult:
    """Outcome of a single tool execution.

    Attributes:
        ok: True when the tool completed successfully.
        value: Primary payload (usually a string for LLM observation).
        error: Human/LLM-facing error message when ok is False.
        metadata: Non-secret auxiliary info (duration hints, tool name, etc.).
            Never put credentials, tokens, or raw secrets here.
    """

    ok: bool
    value: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_llm_text(self) -> str:
        """Serialize for LLM / ToolMessage content."""
        if self.ok:
            if self.value is None:
                return ""
            return str(self.value)
        err = self.error if self.error is not None else "Error: tool failed"
        text = str(err)
        # Preserve existing string contract: failures are recognizable
        if text[:5].lower() != "error":
            return f"Error: {text}"
        return text

    def as_tuple(self) -> Tuple[str, bool]:
        """Compatibility shim for callers that expect (text, success)."""
        return self.to_llm_text(), self.ok

    @classmethod
    def success(cls, value: Any = None, **metadata: Any) -> "ToolResult":
        meta = {k: v for k, v in metadata.items() if v is not None}
        return cls(ok=True, value=value, error=None, metadata=meta)

    @classmethod
    def failure(cls, error: str, value: Any = None, **metadata: Any) -> "ToolResult":
        meta = {k: v for k, v in metadata.items() if v is not None}
        return cls(ok=False, value=value, error=error, metadata=meta)

    @classmethod
    def from_legacy(cls, tool_name: str, raw: Any) -> "ToolResult":
        """Adapt a legacy tool return value into ToolResult.

        - ToolResult → returned as-is
        - None → success with empty value
        - str / other → success decided by ``_result_is_success`` string rules
        """
        if isinstance(raw, ToolResult):
            return raw
        if raw is None:
            return cls.success(value="", tool=tool_name)

        text = str(raw)
        # Local import avoids circular import at module load
        from .registry import _result_is_success

        ok = _result_is_success(tool_name, text)
        if ok:
            return cls.success(value=text, tool=tool_name)
        return cls.failure(error=text, value=text, tool=tool_name)


def _safe_metadata(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Drop obviously sensitive keys from metadata before logging/serialization."""
    if not meta:
        return {}
    blocked = {
        "password",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "api_key",
        "authorization",
        "credential",
        "code_verifier",
        "client_secret",
    }
    out: Dict[str, Any] = {}
    for k, v in meta.items():
        lk = str(k).lower()
        if lk in blocked or any(b in lk for b in ("token", "secret", "password", "credential")):
            continue
        out[k] = v
    return out
