"""NALLY Computer Adapter — Slice 2 agent-facing boundary.

Owns: which computer, is it ready, what can it do, exec orchestration.
Does NOT own: routing, planning, ReAct, tool execution, reconnect loop,
file redirection. Those are Slice 3/4.

Chain (009): ToolRegistry → ComputerAdapter → NallPuterClient.
ToolRegistry never becomes the client; transport never leaks into tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .client import ComputerClient
from .models import ComputerError, Health, MachineProfile, PreflightResult
from .orchestrator import ExecRequest, RunResult, exec_orchestrator
from .preflight import CachedPreflight, run_preflight


@dataclass
class ComputerAdapter:
    """Agent-facing computer operations. Preflight-cached, provider-neutral."""

    client: ComputerClient = field(default_factory=ComputerClient)
    _cache: CachedPreflight = field(default_factory=CachedPreflight)

    def __init__(self, client: Optional[ComputerClient] = None):
        self.client = client or ComputerClient()
        self._cache = CachedPreflight()

    # ── Slice 1: identity + readiness + capability surface ──

    def preflight(self) -> PreflightResult | ComputerError:
        result = run_preflight(self.client, self._cache)
        if isinstance(result, PreflightResult) and result.machine is not None and result.health is not None:
            self._cache.machine = result.machine
            self._cache.health = result.health
            self._cache.last_uptime_sec = result.health.uptime_sec
        return result

    def invalidate(self) -> None:
        """Drop cached profile. Called on uptime reset or machine mismatch."""
        self._cache = CachedPreflight()

    @property
    def computer_id(self) -> str:
        return self._cache.machine.computer_id if self._cache.machine else ""

    @property
    def machine(self) -> Optional[MachineProfile]:
        return self._cache.machine

    @property
    def health(self) -> Optional[Health]:
        return self._cache.health

    def describe(self) -> Dict[str, Any]:
        """What can this computer do? Branch on these, never provider."""
        machine = self._cache.machine
        health = self._cache.health
        if machine is None:
            return {"ready": False, "reason": "no preflight yet — call preflight() first"}
        return {
            "ready": health is not None and health.status == "ok",
            "computer_id": machine.computer_id,
            "persistence": {
                "instance": machine.persistence.instance,
                "workspace": machine.persistence.workspace,
                "workspace_mechanism": machine.persistence.workspace_mechanism,
                "packages": machine.persistence.packages,
            },
            "capabilities": {
                "shell": machine.capabilities.shell,
                "files": machine.capabilities.files,
                "package_install": machine.capabilities.package_install,
                "network": machine.capabilities.network,
                "egress_policy": machine.capabilities.egress_policy,
                "streaming": machine.capabilities.streaming,
                "pause_resume": machine.capabilities.pause_resume,
                "snapshot_restore": machine.capabilities.snapshot_restore,
            },
            "resources": {
                "cpu_millicores": machine.resources.cpu_millicores,
                "memory_mb": machine.resources.memory_mb,
                "disk_gb": machine.resources.disk_gb,
                "pids": machine.resources.pids,
                "wall_time_sec": machine.resources.wall_time_sec,
                "max_output_bytes": machine.resources.max_output_bytes,
                "workspace_gb": machine.resources.workspace_gb,
            },
            "restart_behavior": machine.restart_behavior,
            "sync_state": health.sync_state if health else "unknown",
            "uptime_sec": health.uptime_sec if health else None,
        }

    # ── Slice 2: exec orchestration ──

    def exec(
        self,
        command: str,
        *,
        cwd: Optional[str] = None,
        timeout_sec: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> RunResult | ComputerError:
        """Execute a command and poll until terminal.

        Requires preflight to have succeeded (computer_id must be cached).
        Returns RunResult on terminal status, ComputerError on failure.
        """
        if not self._cache.machine:
            return ComputerError(code="no_preflight", message="call preflight() before exec")
        req = ExecRequest(
            computer_id=self._cache.machine.computer_id,
            command=command,
            cwd=cwd,
            timeout_sec=timeout_sec,
            env=env,
        )
        return exec_orchestrator(
            self.client,
            req,
            idempotency_key=idempotency_key,
            max_wall_time_sec=self._cache.machine.resources.wall_time_sec if self._cache.machine else None,
        )

    def cancel(self, run_id: str) -> RunResult | ComputerError:
        """Cancel a running exec. Returns the cancelled RunResult."""
        resp = self.client.cancel_run(run_id)
        if resp.status_code == 200:
            data = resp.json()
            return RunResult(
                run_id=data.get("run_id", run_id),
                computer_id=data.get("computer_id", ""),
                status="cancelled",
                stdout=data.get("stdout") or "",
                stderr=data.get("stderr") or "",
                exit_code=data.get("exit_code"),
            )
        return ComputerError(
            code="cancel_failed",
            message=f"DELETE /exec/{run_id} returned {resp.status_code}",
            details=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {},
        )

    # ── Explicitly NOT in Slice 2 (Slice 3/4 markers, fail loud if called) ──

    def file_read(self, *args: Any, **kwargs: Any) -> ComputerError:  # Slice 4
        return ComputerError(code="not_implemented", message="file_read is Slice 4 — not yet wired")

    def file_write(self, *args: Any, **kwargs: Any) -> ComputerError:  # Slice 4
        return ComputerError(code="not_implemented", message="file_write is Slice 4 — not yet wired")

    def reconnect(self, *args: Any, **kwargs: Any) -> ComputerError:  # Slice 3
        return ComputerError(code="not_implemented", message="reconnect is Slice 3 — not yet wired")
