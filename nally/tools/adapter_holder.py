"""Shared ComputerAdapter holder for tool routing.

Tools check _adapter during execute(). When set, they route through
the adapter instead of local execution. Chain: ToolRegistry → ComputerAdapter → NallPuterClient.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..computer.adapter import ComputerAdapter

_adapter: Optional[ComputerAdapter] = None


def get_adapter() -> Optional[ComputerAdapter]:
    """Get the current ComputerAdapter (None if not wired)."""
    return _adapter


def set_adapter(adapter: Optional[ComputerAdapter]) -> None:
    """Set the ComputerAdapter for tool routing. Pass None to clear."""
    global _adapter
    _adapter = adapter
