"""OAuth 2.0 flow manager for MCP HTTP servers.

Handles dynamic client registration, authorization, token storage,
and provides OAuthClientProvider instances for the MCP SDK.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
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


# ── PKCE Helpers ──────────────────────────────────────────

# In-flight OAuth state: PKCE verifiers + DCR client IDs + state tokens
_pending_pkce: dict[str, dict] = {}


def generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return code_verifier, code_challenge


# ── Notion OAuth (DCR — zero config) ─────────────────────

NOTION_AUTH_ENDPOINT = "https://mcp.notion.com/authorize"
NOTION_TOKEN_ENDPOINT = "https://mcp.notion.com/token"
NOTION_REGISTER_ENDPOINT = "https://mcp.notion.com/register"
NOTION_REDIRECT_URI = "http://localhost:5000/api/oauth/notion/callback"


async def start_notion_oauth(db_path: str) -> str:
    """Start Notion OAuth: DCR → build auth URL → return it for browser redirect."""

    code_verifier, code_challenge = generate_pkce()
    state = secrets.token_urlsafe(16)

    # Dynamic Client Registration
    async with httpx.AsyncClient() as client:
        resp = await client.post(NOTION_REGISTER_ENDPOINT, json={
            "client_name": "Nally",
            "client_uri": "http://localhost:5000",
            "redirect_uris": [NOTION_REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }, timeout=15.0)
        resp.raise_for_status()
        dcr_data = resp.json()

    client_id = dcr_data["client_id"]

    # Store state for callback
    _pending_pkce["notion"] = {
        "code_verifier": code_verifier,
        "client_id": client_id,
        "state": state,
    }

    # Build authorization URL
    from urllib.parse import urlencode
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": NOTION_REDIRECT_URI,
        "scope": "default",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "consent",
    }
    return f"{NOTION_AUTH_ENDPOINT}?{urlencode(params)}"


async def exchange_notion_code(code: str, db_path: str) -> bool:
    """Exchange Notion authorization code for tokens. Returns True on success."""

    state_data = _pending_pkce.pop("notion", None)
    if not state_data:
        logger.warning("No pending Notion OAuth state")
        return False

    async with httpx.AsyncClient() as client:
        resp = await client.post(NOTION_TOKEN_ENDPOINT, data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": state_data["client_id"],
            "redirect_uri": NOTION_REDIRECT_URI,
            "code_verifier": state_data["code_verifier"],
        }, timeout=15.0)

        if resp.status_code != 200:
            logger.error(f"Notion token exchange failed: {resp.status_code} {resp.text}")
            return False

        token_data = resp.json()

    token = OAuthToken(
        access_token=token_data["access_token"],
        token_type=token_data.get("token_type", "bearer"),
        expires_in=token_data.get("expires_in"),
        refresh_token=token_data.get("refresh_token"),
    )

    storage = SQLiteTokenStorage(db_path, "notion")
    await storage.set_tokens(token)
    logger.info("Notion OAuth successful — token stored")
    return True


# ── Google Workspace OAuth (manual client credentials) ────

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REDIRECT_URI = "http://localhost:5000/api/oauth/google/callback"

GOOGLE_SCOPES = {
    "gmail": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose",
    "gdrive": "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file",
    "gcalendar": "https://www.googleapis.com/auth/calendar.events.readonly https://www.googleapis.com/auth/calendar.calendarlist.readonly",
}

# Which Google MCP services share one OAuth token
GOOGLE_SERVICES = ["gmail", "gdrive", "gcalendar"]


def _get_google_credentials() -> tuple[str, str] | None:
    """Read Google client_id and client_secret from env. Returns None if missing."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None
    return client_id, client_secret


async def start_google_oauth(service: str, db_path: str) -> str:
    """Start Google OAuth: build auth URL → return it for browser redirect."""
    creds = _get_google_credentials()
    if not creds:
        raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env")
    client_id, _ = creds

    code_verifier, code_challenge = generate_pkce()
    state = secrets.token_urlsafe(16)
    scope = GOOGLE_SCOPES.get(service, GOOGLE_SCOPES["gmail"])

    # Store state — all Google services share the same OAuth token
    _pending_pkce["google"] = {
        "code_verifier": code_verifier,
        "client_id": client_id,
        "state": state,
        "service": service,
    }

    from urllib.parse import urlencode
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"


async def exchange_google_code(code: str, db_path: str) -> bool:
    """Exchange Google authorization code for tokens. Returns True on success."""

    state_data = _pending_pkce.pop("google", None)
    if not state_data:
        logger.warning("No pending Google OAuth state")
        return False

    creds = _get_google_credentials()
    if not creds:
        return False
    _, client_secret = creds

    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_ENDPOINT, data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": state_data["client_id"],
            "client_secret": client_secret,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "code_verifier": state_data["code_verifier"],
        }, timeout=15.0)

        if resp.status_code != 200:
            logger.error(f"Google token exchange failed: {resp.status_code} {resp.text}")
            return False

        token_data = resp.json()

    token = OAuthToken(
        access_token=token_data["access_token"],
        token_type=token_data.get("token_type", "bearer"),
        expires_in=token_data.get("expires_in"),
        refresh_token=token_data.get("refresh_token"),
    )

    # Store the same token for all Google services
    for svc in GOOGLE_SERVICES:
        storage = SQLiteTokenStorage(db_path, svc)
        await storage.set_tokens(token)

    logger.info("Google OAuth successful — token stored for all Workspace services")
    return True
