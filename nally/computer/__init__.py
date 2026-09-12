"""NALLY Computer Adapter — Slice 3 (models + transport + preflight + exec + reconnect).

Slice 3 answers: which computer, is it ready, what can it do, exec orchestration,
reconnect loop, lifecycle (start/stop/destroy), sync.
No tool redirection (Slice 4).

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
from .reconnect import (
    LifecycleResult,
    ReconnectResult,
    destroy_computer,
    detect_uptime_reset,
    force_sync,
    reconnect,
    start_computer,
    stop_computer,
)

__all__ = [
    "CachedPreflight",
    "Capabilities",
    "Computer",
    "ComputerAdapter",
    "ComputerClient",
    "ComputerError",
    "ExecRequest",
    "Health",
    "LifecycleResult",
    "MachineProfile",
    "Persistence",
    "PreflightResult",
    "ReconnectResult",
    "Resources",
    "RunResult",
    "SyncState",
    "destroy_computer",
    "detect_uptime_reset",
    "exec_orchestrator",
    "force_sync",
    "reconnect",
    "run_preflight",
    "start_computer",
    "stop_computer",
]
