"""Gmail Direct — bypasses the broken Google MCP server, uses Gmail REST API directly."""

import logging

import httpx

from ..config import DATA_DIR
from ..tools.registry import Tool, registry

logger = logging.getLogger("nally.gmail")


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


async def _get_token() -> str | None:
    from ..mcp.oauth import SQLiteTokenStorage

    storage = SQLiteTokenStorage(str(DATA_DIR / "nally.db"), "gmail")
    token = await storage.get_tokens()
    return token.access_token if token else None


async def _gmail_get(path: str, params: dict = None) -> dict:
    token = await _get_token()
    if not token:
        return {"error": "No Gmail token — connect Gmail in Services panel"}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GMAIL_API}{path}", headers={"Authorization": f"Bearer {token}"}, params=params, timeout=15
        )
        return r.json()


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
        return r.json()


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
                "max_results": {
                    "type": "integer",
                    "description": "Max threads to return (default 10, max 50)",
                    "required": False,
                },
            },
        )

    def execute(self, query="", max_results=10) -> str:
        return _run_async(self._run(query, max_results))

    async def _run(self, query, max_results):
        params = {"q": query, "maxResults": min(max_results, 50)}
        data = await _gmail_get("/users/me/threads", params)
        if "error" in data:
            return f"Gmail error: {data['error'].get('message', data['error'])}"
        threads = data.get("threads", [])
        if not threads:
            return "No threads found."
        lines = [f"Found {len(threads)} threads:\n"]
        for t in threads:
            snippet = t.get("snippet", "")
            tid = t.get("id", "")
            lines.append(f"- [{tid}] {snippet}")
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
            return f"Gmail error: {data['error'].get('message', data['error'])}"
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
            if payload.get("mimeType") == "text/plain":
                import base64

                data = payload.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
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
            return f"Gmail error: {data['error'].get('message', data['error'])}"
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
            return f"Gmail error: {data['error'].get('message', data['error'])}"
        return f"Email: {data.get('emailAddress')}\nMessages: {data.get('messagesTotal')}\nThreads: {data.get('threadsTotal')}"


def register():
    registry.register(GmailSearch())
    registry.register(GmailReadThread())
    registry.register(GmailLabels())
    registry.register(GmailProfile())
    logger.info("Gmail direct tools registered (4 tools)")
