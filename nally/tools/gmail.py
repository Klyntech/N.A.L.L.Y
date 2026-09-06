"""Gmail Direct — bypasses the broken Google MCP server, uses Gmail REST API directly."""

import logging
import threading

import httpx

from ..config import DATA_DIR
from .registry import Tool, registry

logger = logging.getLogger("nally.gmail")

# Mutex to prevent concurrent OAuth token refresh (Google refresh tokens are single-use)
_token_lock = threading.Lock()


def _run_async(coro):
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


GMAIL_API = "https://gmail.googleapis.com/gmail/v1"


def _gmail_error_msg(data: dict) -> str:
    """Safely extract error message from Gmail API response."""
    err = data.get("error", "Unknown error")
    if isinstance(err, dict):
        return err.get("message", str(err))
    return str(err)


async def _get_token() -> str | None:
    """Get a valid Gmail access token, refreshing if expired.

    Uses a mutex to prevent concurrent refresh attempts — Google OAuth
    refresh tokens are single-use and a race would invalidate both requests.
    """
    import time

    from ..mcp.oauth import SQLiteTokenStorage

    db = str(DATA_DIR / "nally.db")
    storage = SQLiteTokenStorage(db, "gmail")
    token = await storage.get_tokens()
    if not token:
        return None

    # Check if token is expired — Google access tokens last ~1 hour
    # The stored token has updated_at in the DB row; check via raw query
    import sqlite3

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT updated_at FROM mcp_oauth WHERE service = 'gmail'").fetchone()
    conn.close()

    if row and token.expires_in:
        updated_at = row[0]
        age = time.time() - updated_at
        # Refresh if older than 80% of expiry (safety margin)
        if age < token.expires_in * 0.8:
            return token.access_token

    # Token expired or age unknown — try refresh (with mutex to prevent races)
    if token.refresh_token:
        with _token_lock:
            # Double-check after acquiring lock — another thread may have refreshed
            conn = sqlite3.connect(db)
            row = conn.execute("SELECT updated_at FROM mcp_oauth WHERE service = 'gmail'").fetchone()
            conn.close()
            if row and token.expires_in:
                age = time.time() - row[0]
                if age < token.expires_in * 0.8:
                    # Another thread refreshed it — re-read the token
                    token = await storage.get_tokens()
                    if token:
                        return token.access_token

            refreshed = await _refresh_google_token(token.refresh_token)
            if refreshed:
                return refreshed

    # Refresh failed — return stale token (will get auth error)
    return token.access_token


async def _refresh_google_token(refresh_token: str) -> str | None:
    """Refresh a Google OAuth token. Returns new access token or None."""
    import os

    from ..mcp.oauth import OAuthToken, SQLiteTokenStorage

    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        logger.warning("Cannot refresh Gmail token: missing GOOGLE_CLIENT_ID/SECRET")
        return None

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=15.0,
            )

            if resp.status_code != 200:
                logger.error(f"Gmail token refresh failed: {resp.status_code} {resp.text[:200]}")
                return None

            data = resp.json()
            new_token = OAuthToken(
                access_token=data["access_token"],
                token_type=data.get("token_type", "bearer"),
                expires_in=data.get("expires_in"),
                refresh_token=data.get("refresh_token", refresh_token),
            )

            db = str(DATA_DIR / "nally.db")
            storage = SQLiteTokenStorage(db, "gmail")
            await storage.set_tokens(new_token)
            logger.info("Gmail token refreshed successfully")
            return new_token.access_token

    except Exception as e:
        logger.error(f"Gmail token refresh error: {type(e).__name__}: {e}")
        return None


async def _gmail_get(path: str, params: dict = None) -> dict:
    token = await _get_token()
    if not token:
        return {"error": "No Gmail token — connect Gmail in Services panel"}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GMAIL_API}{path}", headers={"Authorization": f"Bearer {token}"}, params=params, timeout=15
        )
        try:
            return r.json()
        except Exception:
            return {"error": f"Gmail API returned non-JSON (HTTP {r.status_code}): {r.text[:200]}"}


async def _gmail_post(path: str, body: dict = None) -> dict:
    token = await _get_token()
    if not token:
        return {"error": "No Gmail token — connect Gmail in Services panel"}
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GMAIL_API}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body or {},
            timeout=15,
        )
        try:
            return r.json()
        except Exception:
            return {"error": f"Gmail API returned non-JSON (HTTP {r.status_code}): {r.text[:200]}"}


async def _gmail_delete(path: str) -> dict:
    token = await _get_token()
    if not token:
        return {"error": "No Gmail token — connect Gmail in Services panel"}
    async with httpx.AsyncClient() as client:
        r = await client.delete(
            f"{GMAIL_API}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if r.status_code == 204:
            return {"ok": True}
        try:
            return r.json()
        except Exception:
            return {"error": f"Gmail API returned non-JSON (HTTP {r.status_code}): {r.text[:200]}"}


class GmailRead(Tool):
    """Read-only Gmail capability: search, read_thread, labels, profile."""

    def __init__(self):
        super().__init__(
            name="gmail_read",
            description=(
                "Read Gmail. action=search (find threads by query), read_thread "
                "(full messages in a thread), labels (list folders/tags), profile "
                "(account address and counts)."
            ),
            parameters={
                "action": {
                    "type": "string",
                    "description": "Read operation: search, read_thread, labels, profile",
                    "required": True,
                },
                "query": {
                    "type": "string",
                    "description": "Gmail search query (e.g. 'is:unread', 'from:boss@work.com', 'subject:invoice newer_than:30d')",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Max threads to return (default 10, max 50)",
                    "default": 10,
                },
                "thread_id": {
                    "type": "string",
                    "description": "Gmail thread ID (required for read_thread)",
                },
            },
        )

    def execute(self, action="search", query="", num_results=10, thread_id="", **kwargs) -> str:
        return _run_async(self._run(action, query, num_results, thread_id))

    async def _run(self, action, query, num_results, thread_id):
        action = (action or "search").strip().lower()
        if action == "search":
            return await self._search(query, num_results)
        if action == "read_thread":
            return await self._read_thread(thread_id)
        if action == "labels":
            return await self._labels()
        if action == "profile":
            return await self._profile()
        return f"Error: unknown gmail_read action '{action}' (search|read_thread|labels|profile)"

    async def _search(self, query, num_results):
        params = {"q": query, "maxResults": min(num_results, 50)}
        data = await _gmail_get("/users/me/threads", params)
        if "error" in data:
            return f"Gmail error: {_gmail_error_msg(data)}"
        threads = data.get("threads", [])
        if not threads:
            return "No threads found."
        lines = [f"Found {len(threads)} threads:\n"]
        for t in threads:
            tid = t.get("id", "")
            snippet = t.get("snippet", "")
            # Fetch the first message's from header for sender info
            from_header = ""
            try:
                msgs = t.get("messages", [])
                if msgs:
                    first_msg = msgs[0]
                    payload = first_msg.get("payload", {})
                    headers = payload.get("headers", [])
                    for h in headers:
                        name = h.get("name", "").lower()
                        value = h.get("value", "")
                        # Gmail from format: "Name" <email> or just email
                        if name == "from":
                            from_header = value
                            break
            except Exception:
                from_header = ""
            # Truncate snippet if too long
            snip = snippet[:200] + "..." if len(snippet) > 200 else snippet
            # Extract email from "Name" <email> format or use raw value
            if from_header:
                # Try to extract email from "Name" <email@domain> format
                import re
                match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", from_header)
                if match:
                    from_display = match.group(0)
                else:
                    # Use the part after the last < if present
                    if "<" in from_header and ">" in from_header:
                        from_display = from_header.split("<")[-1].split(">")[0]
                    else:
                        from_display = from_header
            else:
                from_display = "Unknown sender"
            lines.append(f"[{tid}] From: {from_display} | {snip}")
        if data.get("nextPageToken"):
            lines.append(f"\nMore results available (next page token: {data['nextPageToken'][:20]}...)")
        return "\n".join(lines)

    async def _read_thread(self, thread_id):
        if not thread_id:
            return "Error: thread_id is required"
        data = await _gmail_get(f"/users/me/threads/{thread_id}", {"format": "full"})
        if "error" in data:
            return f"Gmail error: {_gmail_error_msg(data)}"
        msgs = data.get("messages", [])
        lines = [f"Thread: {thread_id} ({len(msgs)} messages)\n"]
        for i, msg in enumerate(msgs):
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            lines.append(f"--- Message {i + 1} ---")
            lines.append(f"From: {headers.get('from', '?')}")
            lines.append(f"To: {headers.get('to', '?')}")
            lines.append(f"Subject: {headers.get('subject', '?')}")
            lines.append(f"Date: {headers.get('date', '?')}")
            body = self._extract_body(msg.get("payload", {}))
            lines.append(f"\n{body}\n")
        return "\n".join(lines)

    @staticmethod
    def _extract_body(payload):
        parts = payload.get("parts", [])
        if parts:
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    import base64

                    data = part.get("body", {}).get("data", "")
                    if data:
                        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            for part in parts:
                body = GmailRead._extract_body(part)
                if body:
                    return body
        else:
            mime = payload.get("mimeType", "")
            data = payload.get("body", {}).get("data", "")
            if data:
                import base64

                decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                if mime == "text/plain":
                    return decoded
                elif mime == "text/html":
                    # Strip HTML tags for plain text fallback
                    import re
                    text = re.sub(r'<[^>]+>', ' ', decoded)
                    text = re.sub(r'\s+', ' ', text).strip()
                    return text[:2000] + "..." if len(text) > 2000 else text
        return "(no text body)"

    async def _labels(self):
        data = await _gmail_get("/users/me/labels")
        if "error" in data:
            return f"Gmail error: {_gmail_error_msg(data)}"
        labels = data.get("labels", [])
        lines = [f"{len(labels)} labels:\n"]
        for l in labels:
            lines.append(f"  {l['name']} ({l['id']})")
        return "\n".join(lines)

    async def _profile(self):
        data = await _gmail_get("/users/me/profile")
        if "error" in data:
            return f"Gmail error: {_gmail_error_msg(data)}"
        return f"Email: {data.get('emailAddress')}\nMessages: {data.get('messagesTotal')}\nThreads: {data.get('threadsTotal')}"


def _build_mime_message(to: str, subject: str, body: str, from_addr: str = None, cc: str = None, bcc: str = None, in_reply_to: str = None, references: str = None) -> dict:
    """Build a MIME message dict for Gmail API send."""
    import base64
    from email.mime.text import MIMEText

    msg = MIMEText(body, "plain")
    msg["to"] = to
    if from_addr:
        msg["from"] = from_addr
    if cc:
        msg["cc"] = cc
    if bcc:
        msg["bcc"] = bcc
    msg["subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    return {"raw": raw}


class GmailWrite(Tool):
    """Write Gmail capability: send, reply, draft, mark_read, delete.

    Threading safety is runtime-owned: reply derives recipient/subject/
    In-Reply-To from the thread itself (never model-overridable), and send
    never attaches threading headers. Draft (/drafts) and send
    (/messages/send) endpoints are never interchanged.
    """

    def __init__(self):
        super().__init__(
            name="gmail_write",
            description=(
                "Write Gmail. action=send (new email), reply (reply in thread; "
                "recipient/subject derived from thread), draft (save without sending), "
                "mark_read (mark thread read/unread), delete (trash, or permanent=true)."
            ),
            permission="destructive",
            parameters={
                "action": {
                    "type": "string",
                    "description": "Write operation: send, reply, draft, mark_read, delete",
                    "required": True,
                },
                "to": {
                    "type": "string",
                    "description": "Recipient email address(es) for send/draft (comma-separated)",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line for send/draft",
                },
                "body": {
                    "type": "string",
                    "description": "Email body text (required for send/reply/draft)",
                },
                "cc": {
                    "type": "string",
                    "description": "CC recipient(s) for send, comma-separated",
                },
                "thread_id": {
                    "type": "string",
                    "description": "Gmail thread ID (required for reply/mark_read/delete)",
                },
                "unread": {
                    "type": "boolean",
                    "description": "True to mark as unread, False to mark as read (mark_read only)",
                },
                "permanent": {
                    "type": "boolean",
                    "description": "True to permanently delete, False to trash (delete only)",
                },
            },
        )

    def execute(
        self,
        action="send",
        to="",
        subject="",
        body="",
        cc=None,
        thread_id="",
        unread=False,
        permanent=False,
        **kwargs,
    ) -> str:
        return _run_async(
            self._run(action, to, subject, body, cc, thread_id, unread, permanent)
        )

    async def _run(self, action, to, subject, body, cc, thread_id, unread, permanent):
        action = (action or "send").strip().lower()
        if action == "send":
            return await self._send(to, subject, body, cc)
        if action == "reply":
            return await self._reply(thread_id, body)
        if action == "draft":
            return await self._draft(body, to, subject)
        if action == "mark_read":
            return await self._mark_read(thread_id, unread)
        if action == "delete":
            return await self._delete(thread_id, permanent)
        return f"Error: unknown gmail_write action '{action}' (send|reply|draft|mark_read|delete)"

    async def _send(self, to, subject, body, cc):
        if not to:
            return "Error: to is required for send"
        if not subject:
            return "Error: subject is required for send"
        if not body:
            return "Error: body is required for send"
        mime = _build_mime_message(to=to, subject=subject, body=body, cc=cc)
        data = await _gmail_post("/users/me/messages/send", mime)
        if "error" in data:
            return f"Gmail error: {_gmail_error_msg(data)}"
        return f"Sent. Message ID: {data.get('id', '?')}"

    async def _reply(self, thread_id, body):
        if not thread_id:
            return "Error: thread_id is required for reply"
        if not body:
            return "Error: body is required for reply"

        # Fetch the thread to get the last message's headers for threading
        data = await _gmail_get(f"/users/me/threads/{thread_id}", {"format": "metadata", "metadataHeaders": "from,subject,message-id,to"})
        if "error" in data:
            return f"Gmail error: {_gmail_error_msg(data)}"

        messages = data.get("messages", [])
        if not messages:
            return f"Error: thread {thread_id} has no messages"

        last_msg = messages[-1]
        headers = {h["name"].lower(): h["value"] for h in last_msg.get("payload", {}).get("headers", [])}

        reply_to = headers.get("from", "")
        subject = headers.get("subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        message_id = headers.get("message-id", "")

        mime = _build_mime_message(
            to=reply_to,
            subject=subject,
            body=body,
            in_reply_to=message_id,
        )
        mime["threadId"] = thread_id

        result = await _gmail_post("/users/me/messages/send", mime)
        if "error" in result:
            return f"Gmail error: {_gmail_error_msg(result)}"
        return f"Replied to thread {thread_id}. Message ID: {result.get('id', '?')}"

    async def _draft(self, body, to, subject):
        if not body:
            return "Error: body is required for draft"
        mime = _build_mime_message(to=to or "", subject=subject or "(no subject)", body=body)
        data = await _gmail_post("/users/me/drafts", {"message": mime})
        if "error" in data:
            return f"Gmail error: {_gmail_error_msg(data)}"
        draft_id = data.get("id", "?")
        return f"Draft saved. ID: {draft_id}"

    async def _mark_read(self, thread_id, unread):
        if not thread_id:
            return "Error: thread_id is required for mark_read"

        # Gmail uses label manipulation: UNREAD label = unread, remove UNREAD = read
        body = {"removeLabelIds": ["UNREAD"]} if not unread else {"addLabelIds": ["UNREAD"]}
        data = await _gmail_post(f"/users/me/threads/{thread_id}/modify", body)
        if "error" in data:
            return f"Gmail error: {_gmail_error_msg(data)}"
        status = "unread" if unread else "read"
        return f"Thread {thread_id} marked as {status}"

    async def _delete(self, thread_id, permanent):
        if not thread_id:
            return "Error: thread_id is required for delete"

        if permanent:
            data = await _gmail_delete(f"/users/me/threads/{thread_id}")
            if "error" in data:
                return f"Gmail error: {_gmail_error_msg(data)}"
            return f"Thread {thread_id} permanently deleted"
        else:
            data = await _gmail_post(f"/users/me/threads/{thread_id}/trash")
            if "error" in data:
                return f"Gmail error: {_gmail_error_msg(data)}"
            return f"Thread {thread_id} moved to trash"


def register():
    registry.register(GmailRead())
    registry.register(GmailWrite())
    logger.info("Gmail direct tools registered (2 tools)")
