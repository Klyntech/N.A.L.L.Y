"""ComposedResponse — canonical response type for V2 output pipeline.

Every response from the agent core flows through:
    ResponseComposer.compose() → ComposedResponse
    OutputRouter.route()       → RoutedOutput (surface-specific)

This module is pure data — no side effects, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ComposedResponse:
    """Canonical agent response before surface routing.

    This is the single object every surface handler receives.
    Surfaces read ``text`` for content and ``meta`` for routing hints.

    Attributes:
        text: Final plain-text response (already composed, verified).
        channel: Origin channel (e.g. "telegram:123", "web:default").
        intent_class: Harness classification (SIMPLE/COMPLEX/etc.).
        verified: Whether verification passed.
        is_partial: Completion gate fired (already prefixed [TASK NOT COMPLETE]).
        blocked: Guardrail or permission blocked the response.
        block_reason: Why it was blocked (guardrail message or partial reason).
        attachments: File paths or markers to send alongside text.
    """

    text: str
    channel: str = ""
    intent_class: str = ""
    verified: bool = True
    is_partial: bool = False
    blocked: bool = False
    block_reason: str = ""
    attachments: List[str] = field(default_factory=list)

    @property
    def is_ok(self) -> bool:
        """True when the response is complete and unblocked."""
        return self.verified and not self.is_partial and not self.blocked

    @property
    def display_text(self) -> str:
        """Text suitable for user display (includes block prefix if needed)."""
        if self.blocked and self.block_reason:
            return f"[Blocked by guardrail] {self.block_reason}"
        if self.is_partial and self.block_reason:
            return f"[TASK NOT COMPLETE] {self.block_reason}\n\n{self.text}"
        return self.text
