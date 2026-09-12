"""NALLY Computer Adapter — Slice 1 (models + transport + preflight).

Slice 1 answers: which computer, is it ready, what can it do.
No exec orchestration (Slice 2), no reconnect/lifecycle (Slice 3),
no tool redirection (Slice 4).

Chain: ToolRegistry → ComputerAdapter → ComputerClient.
"""

from .adapter import ComputerAdapter
from .client import ComputerClient
from .models import (
    Capabilities,
    Computer,
    ComputerError,
    Health,
    MachineProfile,
    Persistence,
    PreflightResult,
    Resources,
    SyncState,
)
from .preflight import CachedPreflight, run_preflight

__all__ = [
    "CachedPreflight",
    "Capabilities",
    "Computer",
    "ComputerAdapter",
    "ComputerClient",
    "ComputerError",
    "Health",
    "MachineProfile",
    "Persistence",
    "PreflightResult",
    "Resources",
    "SyncState",
    "run_preflight",
]
