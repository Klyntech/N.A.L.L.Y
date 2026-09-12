"""NALLY Computer Adapter — Slice 2 execution orchestrator.

Owns: idempotency, 500ms poll+jitter, cursor paging, cancel, policy_denied surfacing.
Does NOT own: routing, planning, reconnect, file ops. Those are Slice 3/4.

009 §3 is the authority for all polling/timeout/cancel semantics.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .client import ComputerClient
from .models import ComputerError

# ── Poll constants (009 §3) ──

_POLL_INTERVAL_MS = 500
_POLL_JITTER_MS = 100
_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "timed_out", "cancelled", "policy_denied"})
_POLL_STATUSES = frozenset({"queued", "running"})


@dataclass
class ExecRequest:
    """Execution request — maps to POST /v1/exec body."""

    computer_id: str
    command: str
    cwd: Optional[str] = None
    timeout_sec: Optional[int] = None
    env: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "computer_id": self.computer_id,
            "command": self.command,
        }
        if self.cwd is not None:
            body["cwd"] = self.cwd
        if self.timeout_sec is not None:
            body["timeout_sec"] = self.timeout_sec
        if self.env is not None:
            body["env"] = self.env
        return body


@dataclass
class RunResult:
    """Final output after polling completes."""

    run_id: str
    computer_id: str
    status: str
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    truncated: bool = False
    total_bytes: int = 0
    wall_time_ms: Optional[int] = None
    policy_result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    environment: Optional[Dict[str, Any]] = None
    sync_pending: Optional[bool] = None


def _poll_delay() -> float:
    """500ms ± 100ms jitter (009 §3)."""
    return (_POLL_INTERVAL_MS + random.randint(-_POLL_JITTER_MS, _POLL_JITTER_MS)) / 1000.0


def _parse_run(data: Dict[str, Any]) -> RunResult:
    """Parse a Run JSON dict into RunResult."""
    return RunResult(
        run_id=data.get("run_id", ""),
        computer_id=data.get("computer_id", ""),
        status=data.get("status", "unknown"),
        stdout=data.get("stdout") or "",
        stderr=data.get("stderr") or "",
        exit_code=data.get("exit_code"),
        truncated=data.get("truncated", False),
        total_bytes=data.get("bytes", 0),
        wall_time_ms=data.get("wall_time_ms"),
        policy_result=data.get("policy_result"),
        error=data.get("error"),
        environment=data.get("environment"),
        sync_pending=data.get("sync_pending"),
    )


def _fetch_stdout_pages(
    client: ComputerClient,
    run_id: str,
    first_run: RunResult,
) -> RunResult:
    """If truncated, paginate cursor until all stdout is collected.

    009 §3: cursor/limit paging is mandatory when truncated: true.
    Adapter concatenates pages by next_cursor and returns unified stdout.
    """
    if not first_run.truncated:
        return first_run

    stdout_parts: List[str] = [first_run.stdout]
    cursor = first_run.total_bytes  # next_cursor from first page

    while cursor is not None:
        resp = client.get_run(run_id, cursor=cursor, limit=100_000)
        if resp.status_code != 200:
            break
        page = _parse_run(resp.json())
        if page.stdout:
            stdout_parts.append(page.stdout)
        cursor = page.total_bytes if page.truncated else None

    combined = RunResult(
        run_id=first_run.run_id,
        computer_id=first_run.computer_id,
        status=first_run.status,
        stdout="".join(stdout_parts),
        stderr=first_run.stderr,
        exit_code=first_run.exit_code,
        truncated=False,  # fully fetched
        total_bytes=first_run.total_bytes,
        wall_time_ms=first_run.wall_time_ms,
        policy_result=first_run.policy_result,
        error=first_run.error,
        environment=first_run.environment,
        sync_pending=first_run.sync_pending,
    )
    return combined


def exec_orchestrator(
    client: ComputerClient,
    req: ExecRequest,
    *,
    idempotency_key: Optional[str] = None,
    max_wall_time_sec: Optional[int] = None,
) -> RunResult | ComputerError:
    """Execute a command and poll until terminal.

    Flow (009 §3):
      POST /exec → 201 {run_id}
      poll GET /exec/{run_id} every 500ms (jitter ±100ms) while status ∈ {queued,running}
      cursor/limit paging when truncated
      terminal ∈ {succeeded,failed,timed_out,cancelled,policy_denied}

    Args:
        client: Authenticated NallPuterClient.
        req: Execution request.
        idempotency_key: Reused across retries of the same logical exec.
        max_wall_time_sec: Client-side wall time cap (independent of server wall_time_sec).

    Returns:
        RunResult on terminal status, ComputerError on transport/policy failure.
    """
    key = idempotency_key or ComputerClient.new_idempotency_key()

    # POST /exec → 201 {run_id}
    resp = client.exec(req.to_dict(), idempotency_key=key)

    if resp.status_code == 201:
        data = resp.json()
        run_id = data.get("run_id", "")
    elif resp.status_code == 403:
        # policy_denied at creation — surface immediately
        body = resp.json()
        return ComputerError(
            code="policy_denied",
            message=body.get("message", "policy denied at exec creation"),
            details=body,
        )
    elif resp.status_code == 429:
        return ComputerError(
            code="concurrency_limited",
            message="too many concurrent runs — retry after backoff",
            details=resp.json(),
        )
    elif resp.status_code == 410:
        return ComputerError(
            code="gone",
            message="run evicted — re-exec with new idempotency key",
            details=resp.json(),
        )
    else:
        return ComputerError(
            code="exec_create_failed",
            message=f"POST /exec returned {resp.status_code}",
            details=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {},
        )

    # Poll until terminal
    wall_start = time.monotonic()
    last_run: Optional[RunResult] = None

    while True:
        poll_resp = client.get_run(run_id)
        if poll_resp.status_code != 200:
            return ComputerError(
                code="poll_failed",
                message=f"GET /exec/{run_id} returned {poll_resp.status_code}",
                details=poll_resp.json()
                if poll_resp.headers.get("content-type", "").startswith("application/json")
                else {},
            )

        current = _parse_run(poll_resp.json())
        last_run = current

        if current.status in _TERMINAL_STATUSES:
            break

        # Client-side wall time cap
        if max_wall_time_sec is not None:
            elapsed = time.monotonic() - wall_start
            if elapsed > max_wall_time_sec:
                # Cancel the run, then surface timeout
                client.cancel_run(run_id)
                return RunResult(
                    run_id=run_id,
                    computer_id=req.computer_id,
                    status="timed_out",
                    stdout=current.stdout,
                    stderr=current.stderr,
                    exit_code=current.exit_code,
                    truncated=current.truncated,
                    total_bytes=current.total_bytes,
                    wall_time_ms=int(elapsed * 1000),
                    policy_result={"decision": "deny", "reason": "client_wall_time_exceeded"},
                )

        time.sleep(_poll_delay())

    # Fetch remaining pages if truncated
    result = _fetch_stdout_pages(client, run_id, last_run)

    # Surface policy_denied with full context (009 §3)
    if result.status == "policy_denied" and result.policy_result is None:
        result.policy_result = {"decision": "deny", "reason": "unknown_policy"}

    return result
