"""NALLY Computer Adapter — Slice 1 models.

Provider-neutral mirrors of NallPuter openapi.yaml v0.1 + 009.
No provider branching. No transport here. No tool redirection.

Authority: 009-nally-integration.md + docs/api/openapi.yaml (MachineProfile,
Health, Computer, SyncState). 009 TypeScript sketch is illustrative only;
these dataclasses are the Python-native contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

SyncStateLit = Literal["synced", "pending", "degraded", "env_replay_failed"]
HealthStatus = Literal["ok", "degraded", "recovering"]
ComputerState = Literal[
    "creating",
    "running",
    "idle",
    "stopping",
    "stopped",
    "starting",
    "error",
    "recovering",
    "destroyed",
    "destroying",
]


@dataclass(frozen=True)
class Persistence:
    instance: str = "ephemeral"
    workspace: str = "external_canonical"
    workspace_mechanism: Optional[str] = None
    packages: str = "reconstructible"
    snapshots: bool = False


@dataclass(frozen=True)
class Resources:
    cpu_millicores: int = 500
    memory_mb: int = 512
    disk_gb: int = 2
    pids: int = 100
    wall_time_sec: int = 300
    max_output_bytes: int = 100000
    workspace_gb: int = 1


@dataclass(frozen=True)
class Capabilities:
    shell: bool = True
    files: bool = True
    package_install: bool = True
    network: bool = True
    egress_policy: str = "deny-by-default"
    streaming: bool = False
    pause_resume: bool = False
    snapshot_restore: bool = False


@dataclass(frozen=True)
class MachineProfile:
    computer_id: str = ""
    provider: str = ""
    runtime: str = ""
    revision: Optional[str] = None
    created_at: Optional[str] = None
    persistence: Persistence = field(default_factory=Persistence)
    resources: Resources = field(default_factory=Resources)
    capabilities: Capabilities = field(default_factory=Capabilities)
    restart_behavior: str = "instance_recreated"
    ephemeral_paths: list[str] = field(default_factory=list)
    persistent_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MachineProfile:
        data = data or {}
        p = data.get("persistence") or {}
        r = data.get("resources") or {}
        c = data.get("capabilities") or {}
        return cls(
            computer_id=str(data.get("computer_id", "")),
            provider=str(data.get("provider", "")),
            runtime=str(data.get("runtime", "")),
            revision=data.get("revision"),
            created_at=data.get("created_at"),
            persistence=Persistence(
                instance=str(p.get("instance", "ephemeral")),
                workspace=str(p.get("workspace", "external_canonical")),
                workspace_mechanism=p.get("workspace_mechanism"),
                packages=str(p.get("packages", "reconstructible")),
                snapshots=bool(p.get("snapshots", False)),
            ),
            resources=Resources(
                cpu_millicores=int(r.get("cpu_millicores", 500)),
                memory_mb=int(r.get("memory_mb", 512)),
                disk_gb=int(r.get("disk_gb", 2)),
                pids=int(r.get("pids", 100)),
                wall_time_sec=int(r.get("wall_time_sec", 300)),
                max_output_bytes=int(r.get("max_output_bytes", 100000)),
                workspace_gb=int(r.get("workspace_gb", 1)),
            ),
            capabilities=Capabilities(
                shell=bool(c.get("shell", True)),
                files=bool(c.get("files", True)),
                package_install=bool(c.get("package_install", True)),
                network=bool(c.get("network", True)),
                egress_policy=str(c.get("egress_policy", "deny-by-default")),
                streaming=bool(c.get("streaming", False)),
                pause_resume=bool(c.get("pause_resume", False)),
                snapshot_restore=bool(c.get("snapshot_restore", False)),
            ),
            restart_behavior=str(data.get("restart_behavior", "instance_recreated")),
            ephemeral_paths=list(data.get("ephemeral_paths") or []),
            persistent_paths=list(data.get("persistent_paths") or []),
        )


@dataclass(frozen=True)
class Health:
    status: str = "ok"
    computer_id: str = ""
    uptime_sec: int = 0
    sync_state: str = "synced"
    last_sync_rev: Optional[int] = None
    last_sync_at: Optional[str] = None
    last_error: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Health:
        data = data or {}
        return cls(
            status=str(data.get("status", "ok")),
            computer_id=str(data.get("computer_id", "")),
            uptime_sec=int(data.get("uptime_sec", 0) or 0),
            sync_state=str(data.get("sync_state", "synced")),
            last_sync_rev=data.get("last_sync_rev"),
            last_sync_at=data.get("last_sync_at"),
            last_error=data.get("last_error"),
        )


@dataclass(frozen=True)
class SyncState:
    sync_state: str = "synced"
    last_sync_rev: Optional[int] = None
    last_sync_at: Optional[str] = None
    dirty_count: int = 0
    dirty_files: list[str] = field(default_factory=list)
    last_error: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SyncState:
        data = data or {}
        return cls(
            sync_state=str(data.get("sync_state", "synced")),
            last_sync_rev=data.get("last_sync_rev"),
            last_sync_at=data.get("last_sync_at"),
            dirty_count=int(data.get("dirty_count", 0) or 0),
            dirty_files=list(data.get("dirty_files") or []),
            last_error=data.get("last_error"),
        )


@dataclass(frozen=True)
class Computer:
    computer_id: str = ""
    state: str = "running"
    machine: Optional[MachineProfile] = None
    sync_state: Optional[SyncState] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Computer:
        data = data or {}
        machine = data.get("machine")
        sync = data.get("sync_state")
        return cls(
            computer_id=str(data.get("computer_id", "")),
            state=str(data.get("state", "running")),
            machine=MachineProfile.from_dict(machine) if isinstance(machine, dict) else None,
            sync_state=SyncState.from_dict(sync) if isinstance(sync, dict) else None,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass(frozen=True)
class PreflightResult:
    """Outcome of the mandatory machine → health handshake (009 §2)."""

    computer_id: str = ""
    machine: Optional[MachineProfile] = None
    health: Optional[Health] = None
    ready: bool = False
    reason: str = ""
    needs_reconnect: bool = False


@dataclass(frozen=True)
class ComputerError:
    """Structured computer observation. Never collapsed to generic failed (009 §1)."""

    code: str = ""
    message: str = ""
    retryable: bool = False
    status: Optional[int] = None
    policy_result: Optional[Dict[str, Any]] = None
    computer_id: str = ""
    run_id: Optional[str] = None
