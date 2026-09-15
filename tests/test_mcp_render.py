"""Permanent MCP fixes: Render server, GitHub redirect, token refresh, dead-code cleanup."""

import inspect
import sqlite3

from nally.config import MCP_SERVERS


def _get_server(name: str) -> dict:
    return next(s for s in MCP_SERVERS if s["name"] == name)


def test_render_mcp_configured():
    """Render MCP is registered as HTTP + api_key."""
    srv = _get_server("render")
    assert srv["url"] == "https://mcp.render.com/mcp"
    assert srv["transport"] == "http"
    assert srv["auth_mode"] == "api_key"


def test_github_redirect_not_hardcoded():
    """GitHub OAuth redirect follows _base_url() so Render deploys work."""
    import nally.mcp.oauth as oauth_mod

    assert "127.0.0.1" not in oauth_mod.GITHUB_REDIRECT_URI
    assert oauth_mod.GITHUB_REDIRECT_URI.endswith("/api/oauth/github/callback")


def test_refreshable_services():
    """Notion/Google refresh; GitHub does not (long-lived tokens)."""
    from nally.mcp.client import _REFRESHABLE_SERVICES

    assert "notion" in _REFRESHABLE_SERVICES
    assert "github" not in _REFRESHABLE_SERVICES


def test_get_existing_tokens_no_table_no_crash(tmp_path):
    """Missing mcp_oauth table returns None without creating side-effects."""
    from nally.mcp.client import _get_existing_tokens_sync

    db = str(tmp_path / "empty.db")
    assert _get_existing_tokens_sync("render", db) is None
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mcp_oauth'"
        ).fetchone()
        assert row is None
    finally:
        conn.close()


def test_http_transport_owns_client():
    """Streamable factory creates/closes its own httpx client (no leak)."""
    from nally.mcp.client import _http_transport_fallback

    pairs = list(_http_transport_fallback({"url": "https://mcp.render.com/mcp"}, {}))
    names = [n for n, _ in pairs]
    assert "streamable-http" in names
    src = inspect.getsource(_http_transport_fallback)
    assert "httpx.AsyncClient(headers=headers) as http_client" in src


def test_obfus_stub_removed():
    """Dead _extract_from_obfus_mcp stub is gone for good."""
    import nally.tools.design_fetch as df

    assert not hasattr(df, "_extract_from_obfus_mcp")


def test_oauth_ddl_centralized():
    """Single DDL constant — no duplicated CREATE TABLE strings."""
    import nally.mcp.oauth as oauth_mod

    assert hasattr(oauth_mod, "_MCP_OAUTH_DDL")
    assert "CREATE TABLE IF NOT EXISTS mcp_oauth" in oauth_mod._MCP_OAUTH_DDL
