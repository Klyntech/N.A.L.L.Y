"""NALLY Computer Adapter — Slice 1 preflight.

Mandatory handshake before any exec/files work (009 §2):
  GET /machine → validate + cache → GET /health → readiness → ready | reconnect.

No exec here. No tool redirection here. Provider-neutral: validates
persistence/capabilities/resources + restart_behavior, never provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .client import ComputerClient
from .models import ComputerError, Health, MachineProfile, PreflightResult

_VALID_PERSISTENCE_WORKSPACE = {"ephemeral", "persistent", "external_canonical"}
_VALID_PACKAGES = {"ephemeral", "persistent", "reconstructible"}
_READY_HEALTH = {"ok"}
_READY_SYNC = {"synced", "pending"}
_RECONNECT_SYNC = {"degraded", "env_replay_failed"}
_RECONNECT_STATUS = {"degraded", "recovering"}


@dataclass
class CachedPreflight:
    machine: Optional[MachineProfile] = None
    health: Optional[Health] = None
    last_uptime_sec: Optional[int] = None


def _validate_machine(data: Dict[str, Any]) -> MachineProfile:
    machine = MachineProfile.from_dict(data)
    if not machine.computer_id:
        raise ValueError("preflight: machine.computer_id missing")
    if machine.persistence.workspace not in _VALID_PERSISTENCE_WORKSPACE:
        raise ValueError(f"preflight: unexpected persistence.workspace={machine.persistence.workspace!r}")
    if machine.persistence.packages not in _VALID_PACKAGES:
        raise ValueError(f"preflight: unexpected persistence.packages={machine.persistence.packages!r}")
    return machine


def run_preflight(
    client: ComputerClient,
    cache: Optional[CachedPreflight] = None,
) -> PreflightResult | ComputerError:
    """Run machine → health handshake. Returns PreflightResult or ComputerError.

    Side-effect free except HTTP. Caching/invalidation is owned by the adapter;
    this function validates one handshake. Uptime-reset detection compares
    caller-supplied cache.last_uptime_sec against fresh health.uptime_sec.
    """
    try:
        machine_resp = client.get_machine()
    except Exception as e:
        return ComputerError(code="computer_unreachable", message=f"GET /machine failed: {e}", retryable=True)
    if machine_resp.status_code == 401:
        return ComputerError(code="unauthorized", message="invalid bearer token", retryable=False, status=401)
    if machine_resp.status_code != 200:
        return ComputerError(
            code="preflight_machine_failed",
            message=f"GET /machine → {machine_resp.status_code}",
            retryable=True,
            status=machine_resp.status_code,
        )
    try:
        machine = _validate_machine(machine_resp.json())
    except Exception as e:
        return ComputerError(code="preflight_machine_invalid", message=str(e), retryable=False)

    try:
        health_resp = client.get_health()
    except Exception as e:
        return ComputerError(
            code="computer_unreachable",
            message=f"GET /health failed: {e}",
            retryable=True,
            computer_id=machine.computer_id,
        )
    if health_resp.status_code not in (200, 503):
        return ComputerError(
            code="preflight_health_failed",
            message=f"GET /health → {health_resp.status_code}",
            retryable=True,
            status=health_resp.status_code,
            computer_id=machine.computer_id,
        )
    try:
        health = Health.from_dict(health_resp.json())
    except Exception as e:
        return ComputerError(
            code="preflight_health_invalid",
            message=f"health decode failed: {e}",
            retryable=True,
            computer_id=machine.computer_id,
        )

    if health.computer_id and health.computer_id != machine.computer_id:
        return ComputerError(
            code="preflight_computer_mismatch",
            message="machine.computer_id != health.computer_id",
            retryable=False,
            computer_id=machine.computer_id,
        )

    if cache is not None and cache.last_uptime_sec is not None:
        if health.uptime_sec < cache.last_uptime_sec:
            return PreflightResult(
                computer_id=machine.computer_id,
                machine=machine,
                health=health,
                ready=False,
                reason="uptime reset — possible instance replacement",
                needs_reconnect=True,
            )

    if health.status in _RECONNECT_STATUS or health.sync_state in _RECONNECT_SYNC:
        return PreflightResult(
            computer_id=machine.computer_id,
            machine=machine,
            health=health,
            ready=False,
            reason=f"health {health.status}/{health.sync_state} — enter reconnect, do not execute",
            needs_reconnect=True,
        )

    if health.status not in _READY_HEALTH or health.sync_state not in _READY_SYNC:
        return PreflightResult(
            computer_id=machine.computer_id,
            machine=machine,
            health=health,
            ready=False,
            reason=f"health not ready: {health.status}/{health.sync_state}",
            needs_reconnect=True,
        )

    return PreflightResult(
        computer_id=machine.computer_id,
        machine=machine,
        health=health,
        ready=True,
        reason="ok",
        needs_reconnect=False,
    )
