"""NALLY Computer Adapter — Slice 2 (models + transport + preflight + exec).

Slice 2 answers: which computer, is it ready, what can it do, exec orchestration.
No reconnect/lifecycle (Slice 3), no tool redirection (Slice 4).

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
from .orchestrator import ExecRequest, RunResult, exec_orchestrator
from .preflight import CachedPreflight, run_preflight

__all__ = [
    "CachedPreflight",
    "Capabilities",
    "Computer",
    "ComputerAdapter",
    "ComputerClient",
    "ComputerError",
    "ExecRequest",
    "Health",
    "MachineProfile",
    "Persistence",
    "PreflightResult",
    "Resources",
    "RunResult",
    "SyncState",
    "exec_orchestrator",
    "run_preflight",
]
