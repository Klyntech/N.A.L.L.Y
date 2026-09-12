"""NALLY Computer Adapter — Slice 1 transport.

HTTP transport only. No routing, no planning, no tool semantics.
Provider-neutral: branches on persistence/capabilities/resources, never provider.

Authority: 009 §1 (base URL env, Bearer verbatim, private networking only,
Idempotency-Key per logical op, timeouts). Slice 1 covers the preflight
surface (machine/health/computer/sync); exec orchestration is Slice 2,
reconnect/lifecycle is Slice 3. Tool redirection is Slice 4 — not here.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


def _base_url(explicit: Optional[str] = None) -> str:
    return (explicit or os.getenv("NALLPUTER_URL", "") or "http://localhost:8000/v1").rstrip("/")


def _token(explicit: Optional[str] = None) -> str:
    return explicit or os.getenv("NALLPUTER_TOKEN", "")


def _startup_grace_ms(explicit: Optional[int] = None) -> int:
    if explicit is not None:
        return explicit
    try:
        return int(os.getenv("NALLPUTER_STARTUP_GRACE_MS", "30000"))
    except ValueError:
        return 30000


@dataclass
class ComputerClient:
    """Thin authenticated HTTP surface. No caching, no readiness logic."""

    base_url: str = ""
    token: str = ""
    startup_grace_ms: int = 30000
    timeout_connect: float = 3.0
    timeout_health: float = 5.0
    timeout_ttfb: float = 10.0

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        startup_grace_ms: Optional[int] = None,
    ):
        self.base_url = _base_url(base_url)
        self.token = _token(token)
        self.startup_grace_ms = _startup_grace_ms(startup_grace_ms)
        self.timeout_connect = 3.0
        self.timeout_health = 5.0
        self.timeout_ttfb = 10.0

    def _headers(self, idempotency_key: Optional[str] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _request(
        self,
        method: str,
        path: str,
        timeout: Optional[float] = None,
        idempotency_key: Optional[str] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=timeout or self.timeout_ttfb) as client:
            return client.request(
                method,
                url,
                headers=self._headers(idempotency_key),
                json=json_body,
            )

    @staticmethod
    def new_idempotency_key() -> str:
        return str(uuid.uuid4())

    # ── Machine contract (009 §1, Slice 1) ──

    def get_machine(self) -> httpx.Response:
        return self._request("GET", "/machine", timeout=self.timeout_ttfb)

    def get_health(self) -> httpx.Response:
        return self._request("GET", "/health", timeout=self.timeout_health)

    # ── Computer lifecycle reads (Slice 1; writes are thin wrappers, no orchestration) ──

    def get_computer(self, computer_id: str) -> httpx.Response:
        return self._request("GET", f"/computer/{computer_id}", timeout=self.timeout_ttfb)

    def get_sync(self, computer_id: str) -> httpx.Response:
        return self._request("GET", f"/computer/{computer_id}/sync", timeout=self.timeout_ttfb)

    def create_computer(self, resources: Optional[Dict[str, Any]] = None) -> httpx.Response:
        body: Dict[str, Any] = {}
        if resources:
            body["resources"] = resources
        return self._request("POST", "/computer", timeout=self.timeout_ttfb, json_body=body or None)

    def start_computer(self, computer_id: str) -> httpx.Response:
        return self._request("POST", f"/computer/{computer_id}/start", timeout=self.timeout_ttfb)

    def stop_computer(self, computer_id: str) -> httpx.Response:
        return self._request("POST", f"/computer/{computer_id}/stop", timeout=self.timeout_ttfb)

    def destroy_computer(self, computer_id: str, idempotency_key: Optional[str] = None) -> httpx.Response:
        return self._request(
            "POST",
            f"/computer/{computer_id}/destroy",
            timeout=self.timeout_ttfb,
            idempotency_key=idempotency_key or self.new_idempotency_key(),
        )

    def force_sync(self, computer_id: str) -> httpx.Response:
        return self._request("POST", f"/computer/{computer_id}/sync", timeout=self.timeout_ttfb)

    # ── Execution (009 §1, Slice 2) ──

    def exec(
        self,
        req: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> httpx.Response:
        return self._request(
            "POST",
            "/exec",
            timeout=self.timeout_ttfb,
            idempotency_key=idempotency_key or self.new_idempotency_key(),
            json_body=req,
        )

    def get_run(
        self,
        run_id: str,
        cursor: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> httpx.Response:
        params: Dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        if limit is not None:
            params["limit"] = limit
        url = f"/exec/{run_id}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"
        return self._request("GET", url, timeout=self.timeout_ttfb)

    def cancel_run(self, run_id: str) -> httpx.Response:
        return self._request("DELETE", f"/exec/{run_id}", timeout=self.timeout_ttfb)
