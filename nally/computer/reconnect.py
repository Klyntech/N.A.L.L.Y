"""NALLY Computer Adapter — Slice 3 reconnection and lifecycle.

Owns: uptime reset detection, 503 backoff loop, reconcile, start/stop/destroy.
Does NOT own: exec orchestration (Slice 2), tool redirection (Slice 4).

009 §4 is the authority for all reconnection semantics.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .client import ComputerClient
from .models import ComputerError, Health, MachineProfile

# ── Reconnect constants (009 §4) ──

_BACKOFF_DELAYS_MS = [1000, 2000, 5000, 10_000, 10_000, 10_000]
_BACKOFF_JITTER_MS = 500
_BACKOFF_DEADLINE_SEC = 60


@dataclass
class ReconnectResult:
    """Outcome of a reconnect attempt."""

    success: bool
    computer_id: str
    message: str = ""
    machine: Optional[MachineProfile] = None
    health: Optional[Health] = None


def _backoff_delay() -> float:
    """Pick next delay from sequence, capped at 10s, with ±500ms jitter."""
    delay_ms = random.choice(_BACKOFF_DELAYS_MS)
    jitter = random.randint(-_BACKOFF_JITTER_MS, _BACKOFF_JITTER_MS)
    return (delay_ms + jitter) / 1000.0


def detect_uptime_reset(
    cached_uptime: Optional[int],
    current_uptime: Optional[int],
) -> bool:
    """True if uptime dropped significantly — signals instance replacement."""
    if cached_uptime is None or current_uptime is None:
        return False
    # Uptime dropped by more than 5s — not just a counter wrap
    return current_uptime < cached_uptime - 5


def reconnect(
    client: ComputerClient,
    computer_id: str,
    *,
    cached_uptime: Optional[int] = None,
    on_reconnect: Optional[Any] = None,
) -> ReconnectResult:
    """Reconnect loop (009 §4).

    Detects instance replacement via uptime reset or 503, then polls
    until health ok + sync_state synced|pending, capped at 60s.

    Args:
        client: Authenticated NallPuterClient.
        computer_id: Expected computer_id (never invented on reconnect).
        cached_uptime: Previous uptime_sec for reset detection.
        on_reconnect: Optional callback(profile, health) after successful reconnect.

    Returns:
        ReconnectResult with success=True and refreshed profile, or
        success=False with error details.
    """
    deadline = time.monotonic() + _BACKOFF_DEADLINE_SEC
    last_error = ""

    while time.monotonic() < deadline:
        delay = _backoff_delay()
        time.sleep(delay)

        # GET /machine — confirm same computer_id, re-cache profile
        machine_resp = client.get_machine()
        if machine_resp.status_code == 200:
            machine_data = machine_resp.json()
            if machine_data.get("computer_id") != computer_id:
                return ReconnectResult(
                    success=False,
                    computer_id=computer_id,
                    message="computer_id mismatch during reconnect — possible replacement",
                )
            machine = MachineProfile.from_dict(machine_data)
        else:
            last_error = f"GET /machine returned {machine_resp.status_code}"
            continue

        # GET /health — wait for status: ok, sync_state: synced|pending
        health_resp = client.get_health()
        if health_resp.status_code == 503:
            last_error = "GET /health returned 503 — store degraded"
            continue
        if health_resp.status_code != 200:
            last_error = f"GET /health returned {health_resp.status_code}"
            continue
        health = Health.from_dict(health_resp.json())

        if health.status != "ok":
            last_error = f"health.status={health.status} — waiting for ok"
            continue
        if health.sync_state in ("degraded", "env_replay_failed"):
            last_error = f"sync_state={health.sync_state} — waiting for recovery"
            continue

        # GET /computer/{id} — confirm state: running|idle
        comp_resp = client.get_computer(computer_id)
        if comp_resp.status_code == 404:
            return ReconnectResult(
                success=False,
                computer_id=computer_id,
                message="computer destroyed during reconnect — must create new instance",
            )
        if comp_resp.status_code != 200:
            last_error = f"GET /computer returned {comp_resp.status_code}"
            continue
        comp_data = comp_resp.json()
        if comp_data.get("state") not in ("running", "idle"):
            last_error = f"computer.state={comp_data.get('state')} — waiting for running|idle"
            continue

        # Success — all checks passed
        result = ReconnectResult(
            success=True,
            computer_id=computer_id,
            message="reconnected",
            machine=machine,
            health=health,
        )
        if on_reconnect is not None:
            on_reconnect(machine, health)
        return result

    return ReconnectResult(
        success=False,
        computer_id=computer_id,
        message=f"reconnect deadline exceeded ({_BACKOFF_DEADLINE_SEC}s) — last error: {last_error}",
    )


@dataclass
class LifecycleResult:
    """Outcome of a lifecycle operation (start/stop/destroy)."""

    success: bool
    computer_id: str
    state: str = ""
    message: str = ""


def start_computer(client: ComputerClient, computer_id: str) -> LifecycleResult:
    """Start a stopped computer. Waits for running state."""
    resp = client.start_computer(computer_id)
    if resp.status_code == 200:
        data = resp.json()
        return LifecycleResult(
            success=True,
            computer_id=computer_id,
            state=data.get("state", "unknown"),
            message="started",
        )
    return LifecycleResult(
        success=False,
        computer_id=computer_id,
        message=f"POST /computer/{computer_id}/start returned {resp.status_code}",
    )


def stop_computer(client: ComputerClient, computer_id: str) -> LifecycleResult:
    """Stop a running computer."""
    resp = client.stop_computer(computer_id)
    if resp.status_code == 200:
        data = resp.json()
        return LifecycleResult(
            success=True,
            computer_id=computer_id,
            state=data.get("state", "unknown"),
            message="stopped",
        )
    return LifecycleResult(
        success=False,
        computer_id=computer_id,
        message=f"POST /computer/{computer_id}/stop returned {resp.status_code}",
    )


def destroy_computer(
    client: ComputerClient,
    computer_id: str,
    *,
    idempotency_key: Optional[str] = None,
) -> LifecycleResult:
    """Destroy a computer (retires computer_id)."""
    resp = client.destroy_computer(computer_id, idempotency_key=idempotency_key)
    if resp.status_code in (200, 204):
        return LifecycleResult(
            success=True,
            computer_id=computer_id,
            state="destroyed",
            message="destroyed",
        )
    return LifecycleResult(
        success=False,
        computer_id=computer_id,
        message=f"POST /computer/{computer_id}/destroy returned {resp.status_code}",
    )


def force_sync(client: ComputerClient, computer_id: str) -> Dict[str, Any] | ComputerError:
    """Force sync workspace. Returns SyncState dict or error."""
    resp = client.force_sync(computer_id)
    if resp.status_code == 200:
        return resp.json()
    return ComputerError(
        code="sync_failed",
        message=f"POST /computer/{computer_id}/sync returned {resp.status_code}",
    )
