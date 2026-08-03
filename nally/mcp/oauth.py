"""OAuth 2.0 flow manager for MCP HTTP servers.

Handles dynamic client registration, authorization, token storage,
and provides OAuthClientProvider instances for the MCP SDK.

Includes RFC 9470/8414 OAuth discovery for Notion MCP and
SQLite-backed PKCE state persistence to survive server restarts.
"""

import asyncio
import base64
import hashlib
import logging
import os
import secrets
import sqlite3
import time

import httpx

logger = logging.getLogger("nally.mcp.oauth")

# Lazy MCP SDK imports — only fail at runtime if mcp is actually used
try:
    from mcp.client.auth.oauth2 import OAuthClientProvider
    from mcp.shared.auth import (
        OAuthClientInformationFull,
        OAuthClientMetadata,
        OAuthToken,
    )
except ImportError:
    OAuthClientProvider = None  # type: ignore[assignment,misc]
    OAuthClientInformationFull = None  # type: ignore[assignment,misc]
    OAuthClientMetadata = None  # type: ignore[assignment,misc]
    OAuthToken = None  # type: ignore[assignment,misc]

# Pending callback: authorization_code waiting for callback_handler to consume
_pending_callbacks: dict[str, asyncio.Event] = {}
_pending_codes: dict[str, str | None] = {}


# ── Token encryption ──────────────────────────────────────
# Always uses NALLY_CRED_KEY. Never couples to NALLY_ACCESS_TOKEN.
# Plaintext fallback only for first run before .env is loaded.
_FERNET = None


def _get_fernet():
    """Get or create Fernet instance from NALLY_CRED_KEY.

    Lazy-loaded, cached. If NALLY_CRED_KEY is missing, generates
    a key and logs a warning — tokens will be re-encrypted once
    the key is set.
    """
    global _FERNET
    if _FERNET is not None:
        return _FERNET
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning("cryptography package not installed — tokens stored in plaintext")
        return None
    key = os.getenv("NALLY_CRED_KEY", "")
    if not key:
        logger.warning("NALLY_CRED_KEY not set — tokens stored in plaintext until key is provided")
        return None
    try:
        _FERNET = Fernet(key.encode() if isinstance(key, str) else key)
        return _FERNET
    except Exception as e:
        logger.error(f"Invalid NALLY_CRED_KEY: {e}")
        return None


def _encrypt_token(plaintext: str) -> str:
    """Encrypt a token string. Returns plaintext if encryption unavailable."""
    fernet = _get_fernet()
    if fernet is None:
        return plaintext
    return fernet.encrypt(plaintext.encode()).decode()


def _decrypt_token(ciphertext: str) -> str:
    """Decrypt a token string. Returns as-is if not encrypted (migration)."""
    fernet = _get_fernet()
    if fernet is None:
        return ciphertext
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except Exception:
        # Not encrypted yet — treat as plaintext (migration path)
        return ciphertext


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
            decrypted = _decrypt_token(row["tokens"])
            return OAuthToken.model_validate_json(decrypted)
        except Exception:
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        raw = tokens.model_dump_json()
        encrypted = _encrypt_token(raw)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO mcp_oauth (service, tokens, updated_at) VALUES (?, ?, ?)",
            (self.service, encrypted, time.time()),
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
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
    return code_verifier, code_challenge


# ── OAuth State Persistence (SQLite) ──────────────────────

_OAUTH_STATE_TABLE = "mcp_oauth_state"


def _ensure_state_table(db_path: str):
    """Create the oauth_state table if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_OAUTH_STATE_TABLE} (
            service TEXT PRIMARY KEY,
            code_verifier TEXT,
            client_id TEXT,
            state TEXT,
            token_endpoint TEXT,
            auth_endpoint TEXT,
            created_at REAL
        )
    """)
    conn.commit()
    conn.close()


def save_oauth_state(
    db_path: str, service: str, code_verifier: str, client_id: str, state: str, token_endpoint: str, auth_endpoint: str
) -> None:
    """Persist OAuth state to SQLite so it survives server restarts."""
    _ensure_state_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"INSERT OR REPLACE INTO {_OAUTH_STATE_TABLE} "
        "(service, code_verifier, client_id, state, token_endpoint, auth_endpoint, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (service, code_verifier, client_id, state, token_endpoint, auth_endpoint, time.time()),
    )
    conn.commit()
    conn.close()
    logger.debug(f"Saved OAuth state for {service}")


def load_oauth_state(db_path: str, service: str) -> dict | None:
    """Load persisted OAuth state from SQLite. Returns None if not found."""
    _ensure_state_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        f"SELECT code_verifier, client_id, state, token_endpoint, auth_endpoint "
        f"FROM {_OAUTH_STATE_TABLE} WHERE service = ?",
        (service,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "code_verifier": row["code_verifier"],
        "client_id": row["client_id"],
        "state": row["state"],
        "token_endpoint": row["token_endpoint"],
        "auth_endpoint": row["auth_endpoint"],
    }


def clear_oauth_state(db_path: str, service: str) -> None:
    """Remove persisted OAuth state after successful exchange."""
    _ensure_state_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(f"DELETE FROM {_OAUTH_STATE_TABLE} WHERE service = ?", (service,))
    conn.commit()
    conn.close()


# ── OAuth Discovery (RFC 9470/8414) ──────────────────────

# Hardcoded fallback endpoints (used if discovery fails)
NOTION_AUTH_ENDPOINT_FALLBACK = "https://mcp.notion.com/authorize"
NOTION_TOKEN_ENDPOINT_FALLBACK = "https://mcp.notion.com/token"
NOTION_REGISTER_ENDPOINT_FALLBACK = "https://mcp.notion.com/register"
NOTION_REDIRECT_URI = "http://localhost:5000/api/oauth/notion/callback"


async def discover_notion_metadata(mcp_server_url: str = "https://mcp.notion.com/mcp") -> dict:
    """Discover Notion OAuth endpoints via RFC 9470 (Protected Resource) + RFC 8414 (Auth Server).

    Returns dict with keys: authorization_endpoint, token_endpoint, registration_endpoint.
    Falls back to hardcoded Notion endpoints if discovery fails.
    """
    fallback = {
        "authorization_endpoint": NOTION_AUTH_ENDPOINT_FALLBACK,
        "token_endpoint": NOTION_TOKEN_ENDPOINT_FALLBACK,
        "registration_endpoint": NOTION_REGISTER_ENDPOINT_FALLBACK,
    }

    try:
        async with httpx.AsyncClient() as client:
            # Step 1: RFC 9470 — Fetch Protected Resource Metadata
            pr_url = f"{mcp_server_url.rstrip('/')}/.well-known/oauth-protected-resource"
            logger.debug(f"Fetching protected resource metadata: {pr_url}")
            resp = await client.get(pr_url, timeout=10.0)
            if resp.status_code != 200:
                logger.warning(f"Protected resource metadata returned {resp.status_code}, using fallback endpoints")
                return fallback
            pr_data = resp.json()

            auth_servers = pr_data.get("authorization_servers", [])
            if not auth_servers:
                logger.warning("No authorization_servers in protected resource metadata, using fallback")
                return fallback
            auth_server_url = auth_servers[0]

            # Step 2: RFC 8414 — Fetch Authorization Server Metadata
            as_url = f"{auth_server_url.rstrip('/')}/.well-known/oauth-authorization-server"
            logger.debug(f"Fetching auth server metadata: {as_url}")
            resp2 = await client.get(as_url, timeout=10.0)
            if resp2.status_code != 200:
                logger.warning(f"Auth server metadata returned {resp2.status_code}, using fallback")
                return fallback
            as_data = resp2.json()

            result = {
                "authorization_endpoint": as_data.get("authorization_endpoint", fallback["authorization_endpoint"]),
                "token_endpoint": as_data.get("token_endpoint", fallback["token_endpoint"]),
                "registration_endpoint": as_data.get("registration_endpoint", fallback["registration_endpoint"]),
            }
            logger.info(f"Notion OAuth discovery succeeded: auth={result['authorization_endpoint']}")
            return result

    except Exception as e:
        logger.warning(f"Notion OAuth discovery failed ({type(e).__name__}: {e}), using fallback endpoints")
        return fallback


# ── Notion OAuth (DCR + Discovery) ────────────────────────


async def start_notion_oauth(db_path: str) -> str:
    """Start Notion OAuth: discover endpoints → DCR → build auth URL → return it."""

    code_verifier, code_challenge = generate_pkce()
    state = secrets.token_urlsafe(16)

    # Discover OAuth endpoints (RFC 9470/8414)
    metadata = await discover_notion_metadata()
    auth_endpoint = metadata["authorization_endpoint"]
    token_endpoint = metadata["token_endpoint"]
    register_endpoint = metadata["registration_endpoint"]

    # Dynamic Client Registration
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            register_endpoint,
            json={
                "client_name": "Nally",
                "client_uri": "http://localhost:5000",
                "redirect_uris": [NOTION_REDIRECT_URI],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            timeout=15.0,
        )
        if resp.status_code not in (200, 201):
            logger.error(f"Notion DCR failed: {resp.status_code} {resp.text[:500]}")
            raise ValueError(f"Notion client registration failed ({resp.status_code}): {resp.text[:200]}")
        dcr_data = resp.json()
        logger.info(f"Notion DCR succeeded: client_id={dcr_data.get('client_id', '?')[:8]}...")

    client_id = dcr_data["client_id"]

    # Store state in memory (fast path) + SQLite (survives restarts)
    state_entry = {
        "code_verifier": code_verifier,
        "client_id": client_id,
        "state": state,
        "token_endpoint": token_endpoint,
        "auth_endpoint": auth_endpoint,
    }
    _pending_pkce["notion"] = state_entry
    save_oauth_state(db_path, "notion", code_verifier, client_id, state, token_endpoint, auth_endpoint)

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
    return f"{auth_endpoint}?{urlencode(params)}"


async def exchange_notion_code(code: str, db_path: str) -> bool:
    """Exchange Notion authorization code for tokens. Returns True on success."""

    # Try in-memory first (same-process fast path), fall back to SQLite
    state_data = _pending_pkce.pop("notion", None)
    if not state_data:
        state_data = load_oauth_state(db_path, "notion")
        if state_data:
            logger.debug("Loaded Notion OAuth state from SQLite")
        else:
            logger.warning("No pending Notion OAuth state (memory or SQLite)")
            return False

    token_endpoint = state_data.get("token_endpoint", NOTION_TOKEN_ENDPOINT_FALLBACK)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": state_data["client_id"],
                "redirect_uri": NOTION_REDIRECT_URI,
                "code_verifier": state_data["code_verifier"],
            },
            timeout=15.0,
        )

        if resp.status_code != 200:
            logger.error(f"Notion token exchange failed: {resp.status_code} {resp.text[:500]}")
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

    # Clean up persisted state
    clear_oauth_state(db_path, "notion")

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
    """Start Google OAuth: build auth URL → return it for browser redirect.

    Always requests ALL Google scopes (gmail + drive + calendar) so one
    token covers all Workspace services.
    """
    creds = _get_google_credentials()
    if not creds:
        raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env")
    client_id, _ = creds

    code_verifier, code_challenge = generate_pkce()
    state = secrets.token_urlsafe(16)

    # Combine all scopes — one OAuth flow covers all Google services
    all_scopes = " ".join(GOOGLE_SCOPES.values())

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
        "scope": all_scopes,
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
        resp = await client.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": state_data["client_id"],
                "client_secret": client_secret,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "code_verifier": state_data["code_verifier"],
            },
            timeout=15.0,
        )

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


# ── Higgsfield OAuth ──────────────────────────────────────

HIGGSFIELD_AUTH_ENDPOINT = "https://mcp.higgsfield.ai/oauth2/authorize"
HIGGSFIELD_TOKEN_ENDPOINT = "https://mcp.higgsfield.ai/oauth2/token"
HIGGSFIELD_REGISTER_ENDPOINT = "https://mcp.higgsfield.ai/oauth2/register"
HIGGSFIELD_REDIRECT_URI = "http://localhost:5000/api/oauth/higgsfield/callback"


async def start_higgsfield_oauth(db_path: str) -> str:
    """Start Higgsfield OAuth: discover endpoints → DCR → build auth URL → return it."""

    code_verifier, code_challenge = generate_pkce()
    state = secrets.token_urlsafe(16)

    # Dynamic Client Registration
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            HIGGSFIELD_REGISTER_ENDPOINT,
            json={
                "client_name": "Nally",
                "client_uri": "http://localhost:5000",
                "redirect_uris": [HIGGSFIELD_REDIRECT_URI],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            timeout=15.0,
        )
        if resp.status_code not in (200, 201):
            logger.error(f"Higgsfield DCR failed: {resp.status_code} {resp.text[:500]}")
            raise ValueError(f"Higgsfield client registration failed ({resp.status_code}): {resp.text[:200]}")
        dcr_data = resp.json()
        logger.info(f"Higgsfield DCR succeeded: client_id={dcr_data.get('client_id', '?')[:8]}...")

    client_id = dcr_data["client_id"]

    # Store state
    state_entry = {
        "code_verifier": code_verifier,
        "client_id": client_id,
        "state": state,
        "token_endpoint": HIGGSFIELD_TOKEN_ENDPOINT,
        "auth_endpoint": HIGGSFIELD_AUTH_ENDPOINT,
    }
    _pending_pkce["higgsfield"] = state_entry
    save_oauth_state(
        db_path, "higgsfield", code_verifier, client_id, state, HIGGSFIELD_TOKEN_ENDPOINT, HIGGSFIELD_AUTH_ENDPOINT
    )

    # Build authorization URL
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": HIGGSFIELD_REDIRECT_URI,
        "scope": "openid email offline_access",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "consent",
    }
    return f"{HIGGSFIELD_AUTH_ENDPOINT}?{urlencode(params)}"


async def exchange_higgsfield_code(code: str, db_path: str) -> bool:
    """Exchange Higgsfield authorization code for tokens. Returns True on success."""

    state_data = _pending_pkce.pop("higgsfield", None)
    if not state_data:
        state_data = load_oauth_state(db_path, "higgsfield")
        if state_data:
            logger.debug("Loaded Higgsfield OAuth state from SQLite")
        else:
            logger.warning("No pending Higgsfield OAuth state (memory or SQLite)")
            return False

    token_endpoint = state_data.get("token_endpoint", HIGGSFIELD_TOKEN_ENDPOINT)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": state_data["client_id"],
                "redirect_uri": HIGGSFIELD_REDIRECT_URI,
                "code_verifier": state_data["code_verifier"],
            },
            timeout=15.0,
        )

        if resp.status_code != 200:
            logger.error(f"Higgsfield token exchange failed: {resp.status_code} {resp.text[:500]}")
            return False

        token_data = resp.json()

    token = OAuthToken(
        access_token=token_data["access_token"],
        token_type=token_data.get("token_type", "bearer"),
        expires_in=token_data.get("expires_in"),
        refresh_token=token_data.get("refresh_token"),
    )

    storage = SQLiteTokenStorage(db_path, "higgsfield")
    await storage.set_tokens(token)

    # Clean up persisted state
    clear_oauth_state(db_path, "higgsfield")

    logger.info("Higgsfield OAuth successful — token stored")
    return True
