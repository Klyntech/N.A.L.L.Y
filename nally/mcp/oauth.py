"""OAuth 2.0 flow manager for MCP HTTP servers.

Handles dynamic client registration, authorization, token storage,
and provides OAuthClientProvider instances for the MCP SDK.
"""
import asyncio
import json
import logging
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from mcp.client.auth.oauth2 import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

logger = logging.getLogger("nally.mcp.oauth")

# Pending callback: authorization_code waiting for callback_handler to consume
_pending_callbacks: dict[str, asyncio.Event] = {}
_pending_codes: dict[str, str | None] = {}


class SQLiteTokenStorage:
    """SQLite-backed TokenStorage for OAuth tokens and client registrations."""

    def __init__(self, db_path: str, service: str):
        self.db_path = db_path
        self.service = service
        self._ensure_table()

    def _ensure_table(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mcp_oauth (
                service TEXT PRIMARY KEY,
                tokens TEXT,
                client_info TEXT,
                updated_at REAL
            )
        """)
        conn.commit()
        conn.close()

    def _row(self) -> dict | None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT tokens, client_info FROM mcp_oauth WHERE service = ?",
            (self.service,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return {"tokens": row["tokens"], "client_info": row["client_info"]}

    async def get_tokens(self) -> OAuthToken | None:
        row = self._row()
        if row is None or row["tokens"] is None:
            return None
        try:
            return OAuthToken.model_validate_json(row["tokens"])
        except Exception:
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO mcp_oauth (service, tokens, updated_at) VALUES (?, ?, ?)",
            (self.service, tokens.model_dump_json(), time.time()),
        )
        conn.commit()
        conn.close()
        logger.info(f"Stored tokens for {self.service}")

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        row = self._row()
        if row is None or row["client_info"] is None:
            return None
        try:
            return OAuthClientInformationFull.model_validate_json(row["client_info"])
        except Exception:
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO mcp_oauth (service, client_info, updated_at) VALUES (?, ?, ?)",
            (self.service, client_info.model_dump_json(), time.time()),
        )
        conn.commit()
        conn.close()
        logger.info(f"Stored client info for {self.service}")


async def _make_redirect_handler(service: str):
    """Returns a redirect_handler that stores the auth URL for the frontend."""

    async def redirect_handler(url: str) -> None:
        logger.info(f"OAuth redirect for {service}: {url}")
        _pending_callbacks[service] = asyncio.Event()
        _pending_codes[service] = None
        # Store the URL so the frontend can redirect to it
        _pending_callbacks[service]._auth_url = url  # type: ignore

    return redirect_handler


async def _make_callback_handler(service: str):
    """Returns a callback_handler that waits for the authorization code."""

    async def callback_handler() -> tuple[str, str | None]:
        event = _pending_callbacks.get(service)
        if event is None:
            raise RuntimeError(f"No pending OAuth flow for {service}")
        # Wait for the callback endpoint to deliver the code
        await asyncio.wait_for(event.wait(), timeout=300.0)
        code = _pending_codes.pop(service, None)
        _pending_callbacks.pop(service, None)
        if code is None:
            raise RuntimeError(f"OAuth callback received no code for {service}")
        return code, None

    return callback_handler


def get_auth_url(service: str) -> str | None:
    """Get the pending auth URL for a service (for frontend redirect)."""
    event = _pending_callbacks.get(service)
    if event is not None and hasattr(event, "_auth_url"):
        return event._auth_url  # type: ignore
    return None


def complete_callback(service: str, code: str) -> bool:
    """Deliver an authorization code from the callback endpoint."""
    event = _pending_callbacks.get(service)
    if event is None:
        logger.warning(f"No pending OAuth flow for {service} callback")
        return False
    _pending_codes[service] = code
    event.set()
    return True


async def create_oauth_provider(
    service: str,
    server_url: str,
    db_path: str,
    *,
    scope: str | None = None,
) -> OAuthClientProvider:
    """Create an OAuthClientProvider for a given MCP service."""

    redirect_handler = await _make_redirect_handler(service)
    callback_handler = await _make_callback_handler(service)

    client_metadata = OAuthClientMetadata(
        redirect_uris=["http://localhost:5000/api/oauth/callback"],
        client_name=f"Nally ({service})",
        scope=scope,
    )

    storage = SQLiteTokenStorage(db_path, service)

    provider = OAuthClientProvider(
        server_url=server_url,
        client_metadata=client_metadata,
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )

    return provider


async def get_existing_tokens(service: str, db_path: str) -> OAuthToken | None:
    """Check if a service already has stored tokens."""
    storage = SQLiteTokenStorage(db_path, service)
    return await storage.get_tokens()


def revoke_service(service: str, db_path: str) -> bool:
    """Remove stored tokens for a service."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mcp_oauth (
            service TEXT PRIMARY KEY,
            tokens TEXT,
            client_info TEXT,
            updated_at REAL
        )
    """)
    cursor = conn.execute("DELETE FROM mcp_oauth WHERE service = ?", (service,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0
