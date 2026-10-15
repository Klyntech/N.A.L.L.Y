"""Telegram inline UI — MCP services, connect, and approval keyboards.

Quiet, Telegram-first: short copy, edit-in-place, stable callback prefixes.
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Optional

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..utils.logger import logger

MCP_SERVICES = ("github", "notion", "gmail", "spotify", "render", "nalbridge")

_READY = "●"
_NEED = "○"
_WARN = "!"


def _web_base_url() -> str:
    from ..config import NALLY_BASE_URL

    if NALLY_BASE_URL:
        return NALLY_BASE_URL.rstrip("/")
    port = os.getenv("PORT") or os.getenv("NALLY_PORT") or "5000"
    return f"http://localhost:{port}"


def internal_auth_headers() -> dict[str, str]:
    """Headers required by verify_internal_auth on /api/telegram/* routes."""
    token = os.getenv("NALLY_INTERNAL_TOKEN", "") or ""
    return {
        "X-NALLY-INTERNAL-TOKEN": token,
        "X-NALLY-INTERNAL-TIMESTAMP": str(int(time.time())),
        "X-NALLY-INTERNAL-NONCE": secrets.token_urlsafe(16),
        "Content-Type": "application/json",
    }


def _bearer_headers() -> dict[str, str]:
    token = os.getenv("NALLY_ACCESS_TOKEN", "") or ""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _status_glyph(status: str, connected: bool) -> str:
    if connected or status == "connected":
        return _READY
    if status in (
        "needs_oauth",
        "needs_configuration",
        "needs_mcp_token",
        "token_stored_tools_missing",
        "needs_api_key",
        "configured_tools_missing",
    ):
        return _NEED
    if status in ("error", "failed"):
        return _WARN
    return _NEED


def _status_label(svc: dict) -> str:
    status = (svc.get("status") or "").strip()
    connected = bool(svc.get("connected"))
    tools = svc.get("tools")
    if connected or status == "connected":
        if isinstance(tools, int) and tools > 0:
            return f"ready · {tools} tools"
        return "ready"
    labels = {
        "needs_oauth": "needs auth",
        "needs_configuration": "needs config",
        "needs_mcp_token": "needs token",
        "needs_api_key": "needs API key",
        "token_stored_tools_missing": "token ok · tools missing",
        "configured_tools_missing": "key ok · tools missing",
        "enabled_client_connecting": "connecting…",
    }
    return labels.get(status, status or "unknown")


async def fetch_services() -> list[dict]:
    """GET MCP service list via internal Telegram auth (then bearer fallback)."""
    base = _web_base_url()
    attempts = [
        (f"{base}/api/telegram/mcp/services", internal_auth_headers()),
        (f"{base}/api/mcp/services", _bearer_headers()),
    ]
    last_err: Optional[Exception] = None
    async with httpx.AsyncClient(timeout=20.0) as client:
        for url, headers in attempts:
            try:
                r = await client.get(url, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    services = data.get("services") if isinstance(data, dict) else data
                    if isinstance(services, list):
                        return services
                last_err = RuntimeError(f"HTTP {r.status_code}")
                logger.warning(f"fetch_services {url} → {r.status_code}")
            except Exception as e:
                last_err = e
                logger.debug(f"fetch_services {url} failed: {e}")
    if last_err:
        raise last_err
    return []


async def start_connect(service: str) -> dict:
    service = service.strip().lower()
    if service not in MCP_SERVICES:
        return {"status": "error", "detail": "unsupported service"}
    base = _web_base_url()
    attempts = [
        (f"{base}/api/telegram/mcp/connect", internal_auth_headers(), {"service": service}),
        (f"{base}/api/mcp/connect/{service}", _bearer_headers(), None),
    ]
    last: dict = {"status": "error", "detail": "unreachable"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for url, headers, body in attempts:
            try:
                if body is not None:
                    r = await client.post(url, headers=headers, json=body)
                else:
                    r = await client.post(url, headers=headers)
                if r.status_code < 400:
                    try:
                        return r.json()
                    except Exception:
                        return {"status": "ok", "raw": r.text[:500]}
                detail = f"HTTP {r.status_code}"
                try:
                    err = r.json()
                    if isinstance(err, dict) and err.get("detail"):
                        detail = str(err["detail"])[:400]
                except Exception:
                    if r.text:
                        detail = r.text[:300]
                last = {"status": "error", "detail": detail, "body": r.text[:300]}
            except Exception as e:
                last = {"status": "error", "detail": str(e)}
                logger.debug(f"start_connect {url} failed: {e}")
    return last


def format_mcp_home(services: list[dict]) -> str:
    lines = ["<b>MCP services</b>", "Tap a service to connect or refresh.", ""]
    by_name = {str(s.get("name", "")).lower(): s for s in services if isinstance(s, dict)}
    for name in MCP_SERVICES:
        svc = by_name.get(name, {"name": name, "status": "unknown", "connected": False})
        glyph = _status_glyph(str(svc.get("status", "")), bool(svc.get("connected")))
        lines.append(f"{glyph} <b>{name}</b> — {_status_label(svc)}")
    for name, svc in by_name.items():
        if name not in MCP_SERVICES:
            glyph = _status_glyph(str(svc.get("status", "")), bool(svc.get("connected")))
            lines.append(f"{glyph} <b>{name}</b> — {_status_label(svc)}")
    return "\n".join(lines)


def format_mcp_service(svc: dict, connect_result: Optional[dict] = None) -> str:
    name = str(svc.get("name") or "?")
    glyph = _status_glyph(str(svc.get("status", "")), bool(svc.get("connected")))
    lines = [
        f"<b>{name}</b>",
        f"{glyph} {_status_label(svc)}",
    ]
    desc = (svc.get("description") or "").strip()
    if desc:
        lines.append(desc[:200])
    auth = svc.get("auth_mode")
    if auth:
        lines.append(f"Auth: <code>{auth}</code>")
    tools = svc.get("tools")
    if isinstance(tools, int):
        lines.append(f"Tools loaded: {tools}")

    if connect_result:
        st = connect_result.get("status") or ""
        if connect_result.get("auth_url") or connect_result.get("url"):
            lines.append("")
            lines.append("Auth link ready — open it, then Refresh.")
        elif st in ("connected", "ok", "already_connected"):
            lines.append("")
            lines.append("Connected.")
        elif st == "needs_configuration":
            req = connect_result.get("required_env") or []
            lines.append("")
            lines.append("Needs server config" + (f": <code>{', '.join(req)}</code>" if req else "."))
        elif connect_result.get("detail"):
            lines.append("")
            lines.append(str(connect_result.get("detail"))[:200])
    return "\n".join(lines)


def keyboard_mcp_home(services: list[dict]) -> InlineKeyboardMarkup:
    by_name = {str(s.get("name", "")).lower(): s for s in services if isinstance(s, dict)}
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for name in MCP_SERVICES:
        svc = by_name.get(name, {})
        glyph = _status_glyph(str(svc.get("status", "")), bool(svc.get("connected")))
        row.append(InlineKeyboardButton(f"{glyph} {name}", callback_data=f"mcp:svc:{name}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("Refresh", callback_data="mcp:list")])
    return InlineKeyboardMarkup(rows)


def keyboard_mcp_service(
    name: str,
    *,
    connected: bool = False,
    auth_url: Optional[str] = None,
) -> InlineKeyboardMarkup:
    name = name.strip().lower()
    rows: list[list[InlineKeyboardButton]] = []
    if auth_url:
        rows.append([InlineKeyboardButton("Open auth", url=auth_url)])
    if not connected:
        rows.append([InlineKeyboardButton("Connect", callback_data=f"mcp:conn:{name}")])
    rows.append(
        [
            InlineKeyboardButton("Refresh", callback_data=f"mcp:svc:{name}"),
            InlineKeyboardButton("Back", callback_data="mcp:list"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def keyboard_approval(short_id: str) -> InlineKeyboardMarkup:
    # Telegram callback_data allows up to 64 bytes. Keep the complete tool-call
    # ID: truncating it makes the approval endpoint unable to resolve the pending call.
    sid = str(short_id).strip()
    if not sid or len(sid.encode("utf-8")) > 55:
        raise ValueError("Tool-call ID cannot fit safely in Telegram approval callback data")
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Allow", callback_data=f"appr:y:{sid}"),
                InlineKeyboardButton("Deny", callback_data=f"appr:n:{sid}"),
            ]
        ]
    )


def format_approval(tool: str, args_preview: str = "") -> str:
    lines = ["<b>Permission required</b>", f"Tool: <code>{_esc(tool)}</code>"]
    if args_preview:
        lines.append(f"Args: <code>{_esc(args_preview[:400])}</code>")
    return "\n".join(lines)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def show_mcp_home(message) -> None:
    try:
        services = await fetch_services()
    except Exception as e:
        await message.reply_text(
            f"Could not load services: {e}\n"
            "Check NALLY_INTERNAL_TOKEN is set and matches the server."
        )
        return
    text = format_mcp_home(services)
    kb = keyboard_mcp_home(services)
    await message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def handle_callback(query, context: ContextTypes.DEFAULT_TYPE) -> bool:
    data = (query.data or "").strip()
    if not data:
        return False
    if data.startswith("mcp:"):
        await _handle_mcp_callback(query, data)
        return True
    if data.startswith("appr:"):
        await _handle_approval_callback(query, data)
        return True
    return False


async def _handle_mcp_callback(query, data: str) -> None:
    await query.answer()
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    try:
        if action == "list" or data == "mcp:list":
            services = await fetch_services()
            await query.edit_message_text(
                format_mcp_home(services),
                parse_mode="HTML",
                reply_markup=keyboard_mcp_home(services),
            )
            return

        if action == "svc" and len(parts) >= 3:
            name = parts[2].lower()
            services = await fetch_services()
            by_name = {str(s.get("name", "")).lower(): s for s in services}
            svc = by_name.get(name, {"name": name, "status": "unknown", "connected": False})
            await query.edit_message_text(
                format_mcp_service(svc),
                parse_mode="HTML",
                reply_markup=keyboard_mcp_service(
                    name,
                    connected=bool(svc.get("connected")),
                ),
            )
            return

        if action == "conn" and len(parts) >= 3:
            name = parts[2].lower()
            result = await start_connect(name)
            services = await fetch_services()
            by_name = {str(s.get("name", "")).lower(): s for s in services}
            svc = by_name.get(name, {"name": name, "status": "unknown", "connected": False})
            auth_url = result.get("auth_url") or result.get("url")
            await query.edit_message_text(
                format_mcp_service(svc, connect_result=result),
                parse_mode="HTML",
                reply_markup=keyboard_mcp_service(
                    name,
                    connected=bool(svc.get("connected")),
                    auth_url=auth_url if isinstance(auth_url, str) else None,
                ),
            )
            return

        await query.edit_message_text("Unknown action.")
    except Exception as e:
        logger.error(f"MCP callback failed: {e}")
        try:
            await query.edit_message_text(f"Failed: {e}")
        except Exception:
            pass


async def _handle_approval_callback(query, data: str) -> None:
    await query.answer()
    parts = data.split(":", 2)
    if len(parts) < 3:
        await query.edit_message_text("Invalid approval.")
        return
    approved = parts[1] == "y"
    tc_id = parts[2]
    base = _web_base_url()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"{base}/api/telegram/approve",
                headers=internal_auth_headers(),
                json={"tc_id": tc_id, "approved": approved},
            )
        label = "Allowed" if approved else "Denied"
        if r.status_code >= 400:
            await query.edit_message_text(f"{label} — server HTTP {r.status_code}")
        else:
            await query.edit_message_text(f"{label}.")
    except Exception as e:
        await query.edit_message_text(f"Approval failed: {e}")
