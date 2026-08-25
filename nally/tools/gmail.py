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


class GmailSearch(Tool):
    def __init__(self):
        super().__init__(
            name="gmail_search",
            description="Search Gmail threads. Returns thread IDs, snippets, subjects, senders. Use Gmail query syntax: from:user@example.com, subject:keyword, is:unread, newer_than:7d, has:attachment, in:inbox, etc.",
            parameters={
                "query": {
                    "type": "string",
                    "description": "Gmail search query (e.g. 'is:unread', 'from:boss@work.com', 'subject:invoice newer_than:30d')",
                    "required": False,
                },
                "num_results": {
                    "type": "integer",
                    "description": "Max threads to return (default 10, max 50)",
                    "default": 10,
                },
            },
        )

    def execute(self, query="", num_results=10) -> str:
        return _run_async(self._run(query, num_results))

    async def _run(self, query, num_results):
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


class GmailReadThread(Tool):
    def __init__(self):
        super().__init__(
            name="gmail_read_thread",
            description="Read full messages in a Gmail thread. Returns subject, sender, recipients, date, and body text.",
            parameters={
                "thread_id": {
                    "type": "string",
                    "description": "The Gmail thread ID from gmail_search results",
                    "required": True,
                },
            },
        )

    def execute(self, thread_id="") -> str:
        return _run_async(self._run(thread_id))

    async def _run(self, thread_id):
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

    def _extract_body(self, payload):
        parts = payload.get("parts", [])
        if parts:
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    import base64

                    data = part.get("body", {}).get("data", "")
                    if data:
                        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            for part in parts:
                body = self._extract_body(part)
                if body:
                    return body
        else:
            mime = payload.get("mimeType", "")
            data = payload.get("body", {}).get("data", "")
            if data:
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


class GmailLabels(Tool):
    def __init__(self):
        super().__init__(
            name="gmail_labels",
            description="List all Gmail labels (folders/tags) with their IDs and names.",
            parameters={},
        )

    def execute(self, **kwargs) -> str:
        return _run_async(self._run())

    async def _run(self):
        data = await _gmail_get("/users/me/labels")
        if "error" in data:
            return f"Gmail error: {_gmail_error_msg(data)}"
        labels = data.get("labels", [])
        lines = [f"{len(labels)} labels:\n"]
        for l in labels:
            lines.append(f"  {l['name']} ({l['id']})")
        return "\n".join(lines)


class GmailProfile(Tool):
    def __init__(self):
        super().__init__(
            name="gmail_profile",
            description="Get Gmail account profile (email address, message/thread counts).",
            parameters={},
        )

    def execute(self, **kwargs) -> str:
        return _run_async(self._run())

    async def _run(self):
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


class GmailSend(Tool):
    def __init__(self):
        super().__init__(
            name="gmail_send",
            description="Compose and send a new email via Gmail. Returns the sent message ID on success.",
            permission="destructive",
            parameters={
                "to": {
                    "type": "string",
                    "description": "Recipient email address(es), comma-separated for multiple",
                    "required": True,
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                    "required": True,
                },
                "body": {
                    "type": "string",
                    "description": "Email body text (plain text)",
                    "required": True,
                },
                "cc": {
                    "type": "string",
                    "description": "CC recipient(s), comma-separated",
                },
            },
        )

    def execute(self, to: str, subject: str, body: str, cc: str = None) -> str:
        return _run_async(self._run(to, subject, body, cc))

    async def _run(self, to, subject, body, cc):
        mime = _build_mime_message(to=to, subject=subject, body=body, cc=cc)
        data = await _gmail_post("/users/me/messages/send", mime)
        if "error" in data:
            return f"Gmail error: {_gmail_error_msg(data)}"
        return f"Sent. Message ID: {data.get('id', '?')}"


class GmailReply(Tool):
    def __init__(self):
        super().__init__(
            name="gmail_reply",
            description="Reply to a Gmail thread. Adds your reply to the existing conversation.",
            permission="destructive",
            parameters={
                "thread_id": {
                    "type": "string",
                    "description": "The Gmail thread ID to reply to",
                    "required": True,
                },
                "body": {
                    "type": "string",
                    "description": "Reply body text (plain text)",
                    "required": True,
                },
            },
        )

    def execute(self, thread_id: str, body: str) -> str:
        return _run_async(self._run(thread_id, body))

    async def _run(self, thread_id, body):
        if not thread_id:
            return "Error: thread_id is required"

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


class GmailDraft(Tool):
    def __init__(self):
        super().__init__(
            name="gmail_draft",
            description="Save a draft email without sending. Returns the draft ID.",
            parameters={
                "to": {
                    "type": "string",
                    "description": "Recipient email address(es), comma-separated",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body text (plain text)",
                    "required": True,
                },
            },
        )

    def execute(self, body: str, to: str = "", subject: str = "") -> str:
        return _run_async(self._run(body, to, subject))

    async def _run(self, body, to, subject):
        mime = _build_mime_message(to=to or "", subject=subject or "(no subject)", body=body)
        data = await _gmail_post("/users/me/drafts", {"message": mime})
        if "error" in data:
            return f"Gmail error: {_gmail_error_msg(data)}"
        draft_id = data.get("id", "?")
        return f"Draft saved. ID: {draft_id}"


class GmailMarkRead(Tool):
    def __init__(self):
        super().__init__(
            name="gmail_mark_read",
            description="Mark a Gmail thread as read or unread.",
            parameters={
                "thread_id": {
                    "type": "string",
                    "description": "The Gmail thread ID",
                    "required": True,
                },
                "unread": {
                    "type": "boolean",
                    "description": "True to mark as unread, False to mark as read (default: False = mark as read)",
                },
            },
        )

    def execute(self, thread_id: str, unread: bool = False) -> str:
        return _run_async(self._run(thread_id, unread))

    async def _run(self, thread_id, unread):
        if not thread_id:
            return "Error: thread_id is required"

        # Gmail uses label manipulation: UNREAD label = unread, remove UNREAD = read
        body = {"removeLabelIds": ["UNREAD"]} if not unread else {"addLabelIds": ["UNREAD"]}
        data = await _gmail_post(f"/users/me/threads/{thread_id}/modify", body)
        if "error" in data:
            return f"Gmail error: {_gmail_error_msg(data)}"
        status = "unread" if unread else "read"
        return f"Thread {thread_id} marked as {status}"


class GmailDelete(Tool):
    def __init__(self):
        super().__init__(
            name="gmail_delete",
            description="Delete a Gmail thread (moves to trash). Use permanent=true to permanently delete.",
            permission="destructive",
            parameters={
                "thread_id": {
                    "type": "string",
                    "description": "The Gmail thread ID to delete",
                    "required": True,
                },
                "permanent": {
                    "type": "boolean",
                    "description": "True to permanently delete, False to trash (default: False = trash)",
                },
            },
        )

    def execute(self, thread_id: str, permanent: bool = False) -> str:
        return _run_async(self._run(thread_id, permanent))

    async def _run(self, thread_id, permanent):
        if not thread_id:
            return "Error: thread_id is required"

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
    registry.register(GmailSearch())
    registry.register(GmailReadThread())
    registry.register(GmailLabels())
    registry.register(GmailProfile())
    registry.register(GmailSend())
    registry.register(GmailReply())
    registry.register(GmailDraft())
    registry.register(GmailMarkRead())
    registry.register(GmailDelete())
    logger.info("Gmail direct tools registered (9 tools)")
