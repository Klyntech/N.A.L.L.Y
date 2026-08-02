"""Nally Error Hierarchy — Typed, structured errors for the entire backend.

Every error carries:
  - code: machine-readable identifier ("tool_not_found", "llm_rate_limit")
  - message: human-readable explanation
  - severity: how bad is it ("info" | "warning" | "error" | "critical")
  - retryable: can the caller try again?
  - context: dict with relevant metadata (tool name, attempt number, etc.)

Tools return NallyError instances instead of raw strings.
The agent converts them to LLM-friendly format.
The API layer converts them to JSON responses.
"""

from enum import StrEnum
from typing import Any, Dict, Optional


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NallyError(Exception):
    """Base error for all Nally operations."""

    def __init__(
        self,
        code: str,
        message: str,
        severity: Severity = Severity.ERROR,
        retryable: bool = False,
        context: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.severity = severity
        self.retryable = retryable
        self.context = context or {}
        super().__init__(message)

    def to_llm_format(self) -> str:
        """What the LLM sees when this error occurs.

        Keep it concise — the LLM needs to understand what failed
        and decide whether to retry or take an alternative approach.
        """
        parts = [f"Error: {self.message}"]
        if self.retryable:
            parts.append("(You may retry this operation)")
        return " | ".join(parts)

    def to_api_format(self) -> Dict[str, Any]:
        """What the HTTP response contains.

        Structured for client-side error handling.
        """
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "severity": self.severity.value,
                "retryable": self.retryable,
                "context": self.context,
            },
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code!r}, message={self.message!r})"


# ── Tool Errors ───────────────────────────────────────────


class ToolError(NallyError):
    """Errors from tool execution (not found, failed, timed out)."""

    def __init__(
        self,
        message: str,
        tool_name: str = "",
        code: str = "tool_error",
        severity: Severity = Severity.ERROR,
        retryable: bool = False,
        context: Optional[Dict[str, Any]] = None,
    ):
        ctx = {"tool_name": tool_name, **(context or {})}
        super().__init__(code=code, message=message, severity=severity, retryable=retryable, context=ctx)

    @classmethod
    def not_found(cls, name: str) -> "ToolError":
        return cls(
            message=f"Tool '{name}' not found",
            tool_name=name,
            code="tool_not_found",
            severity=Severity.WARNING,
        )

    @classmethod
    def failed(cls, name: str, reason: str) -> "ToolError":
        return cls(
            message=f"Tool '{name}' failed: {reason}",
            tool_name=name,
            code="tool_failed",
            context={"reason": reason},
        )

    @classmethod
    def timeout(cls, name: str, seconds: int = 30) -> "ToolError":
        return cls(
            message=f"Tool '{name}' timed out after {seconds}s",
            tool_name=name,
            code="tool_timeout",
            retryable=True,
            context={"timeout_seconds": seconds},
        )

    @classmethod
    def blocked(cls, name: str) -> "ToolError":
        return cls(
            message=f"Tool '{name}' is blocked by permission config",
            tool_name=name,
            code="tool_blocked",
            severity=Severity.WARNING,
        )

    @classmethod
    def declined(cls, name: str) -> "ToolError":
        return cls(
            message=f"Tool '{name}' was declined or timed out waiting for approval",
            tool_name=name,
            code="tool_declined",
            severity=Severity.WARNING,
        )

    @classmethod
    def output_too_large(cls, name: str, chars: int, limit: int) -> "ToolError":
        return cls(
            message=f"Tool '{name}' output truncated ({chars} chars, limit {limit})",
            tool_name=name,
            code="tool_output_truncated",
            severity=Severity.INFO,
            context={"chars": chars, "limit": limit},
        )


# ── Permission Errors ─────────────────────────────────────


class PermissionDenied(NallyError):
    """Permission system blocked an operation."""

    def __init__(
        self,
        message: str,
        tool_name: str = "",
        context: Optional[Dict[str, Any]] = None,
    ):
        ctx = {"tool_name": tool_name, **(context or {})}
        super().__init__(
            code="permission_denied",
            message=message,
            severity=Severity.WARNING,
            retryable=False,
            context=ctx,
        )

    @classmethod
    def denied(cls, tool_name: str) -> "PermissionDenied":
        return cls(
            message=f"Permission denied for '{tool_name}'",
            tool_name=tool_name,
        )

    @classmethod
    def timed_out(cls, tool_name: str) -> "PermissionDenied":
        return cls(
            message=f"Approval for '{tool_name}' timed out",
            tool_name=tool_name,
        )


# ── LLM Errors ────────────────────────────────────────────


class LLMError(NallyError):
    """Errors from the LLM provider (rate limits, API failures, etc.)."""

    def __init__(
        self,
        message: str,
        code: str = "llm_error",
        severity: Severity = Severity.ERROR,
        retryable: bool = False,
        provider: str = "",
        model: str = "",
        context: Optional[Dict[str, Any]] = None,
    ):
        ctx = {"provider": provider, "model": model, **(context or {})}
        super().__init__(code=code, message=message, severity=severity, retryable=retryable, context=ctx)

    @classmethod
    def rate_limit(cls, provider: str = "", model: str = "") -> "LLMError":
        return cls(
            message="Rate limit reached. Please wait a moment and try again.",
            code="llm_rate_limit",
            severity=Severity.WARNING,
            retryable=True,
            provider=provider,
            model=model,
        )

    @classmethod
    def overloaded(cls, provider: str = "", model: str = "") -> "LLMError":
        return cls(
            message="The AI model is currently overloaded. Please try again in a moment.",
            code="llm_overloaded",
            severity=Severity.WARNING,
            retryable=True,
            provider=provider,
            model=model,
        )

    @classmethod
    def connection_failed(cls, provider: str = "", reason: str = "") -> "LLMError":
        return cls(
            message=f"Failed to connect to {provider or 'AI provider'}: {reason or 'connection error'}",
            code="llm_connection_failed",
            retryable=True,
            provider=provider,
            context={"reason": reason},
        )

    @classmethod
    def auth_failed(cls, provider: str = "") -> "LLMError":
        return cls(
            message=f"Authentication failed for {provider or 'AI provider'}. Check your API key.",
            code="llm_auth_failed",
            severity=Severity.CRITICAL,
            provider=provider,
        )

    @classmethod
    def circuit_breaker(cls, consecutive_errors: int, total_calls: int) -> "LLMError":
        return cls(
            message=f"Agent stopped after {consecutive_errors} consecutive errors or {total_calls} total tool calls.",
            code="llm_circuit_breaker",
            severity=Severity.ERROR,
            context={"consecutive_errors": consecutive_errors, "total_calls": total_calls},
        )


# ── Memory Errors ─────────────────────────────────────────


class MemoryError(NallyError):
    """Errors from the memory system (database, storage)."""

    def __init__(
        self,
        message: str,
        code: str = "memory_error",
        severity: Severity = Severity.ERROR,
        retryable: bool = False,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(code=code, message=message, severity=severity, retryable=retryable, context=context or {})

    @classmethod
    def db_connection_failed(cls, reason: str = "") -> "MemoryError":
        return cls(
            message=f"Memory database connection failed: {reason or 'unknown error'}",
            code="memory_db_connection",
            context={"reason": reason},
        )

    @classmethod
    def query_failed(cls, operation: str, reason: str = "") -> "MemoryError":
        return cls(
            message=f"Memory query failed ({operation}): {reason or 'unknown error'}",
            code="memory_query_failed",
            context={"operation": operation, "reason": reason},
        )


# ── Config Errors ─────────────────────────────────────────


class ConfigError(NallyError):
    """Errors from configuration (missing keys, invalid values)."""

    def __init__(
        self,
        message: str,
        code: str = "config_error",
        severity: Severity = Severity.ERROR,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(code=code, message=message, severity=severity, context=context or {})

    @classmethod
    def missing_key(cls, key: str) -> "ConfigError":
        return cls(
            message=f"Required configuration '{key}' is not set",
            code="config_missing_key",
            severity=Severity.CRITICAL,
            context={"key": key},
        )

    @classmethod
    def invalid_value(cls, key: str, reason: str = "") -> "ConfigError":
        return cls(
            message=f"Invalid value for '{key}': {reason or 'check your configuration'}",
            code="config_invalid_value",
            context={"key": key, "reason": reason},
        )
