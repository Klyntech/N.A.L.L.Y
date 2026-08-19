"""Phone Calls — Plivo API integration.

Makes outbound phone calls via Plivo. Supports Nigerian numbers (+234)
and 200+ countries. Free trial: $10 credit, no card required.

Get credentials at: https://console.plivo.com
"""

import logging
import os

from .registry import Tool, registry

logger = logging.getLogger("nally.tools.phone")

# Plivo's hosted XML for simple TTS
ANSWER_URL = "https://s3.amazonaws.com/static.plivo.com/answer.xml"


def _get_client():
    auth_id = os.getenv("PLIVO_AUTH_ID", "")
    auth_token = os.getenv("PLIVO_AUTH_TOKEN", "")
    if not auth_id or not auth_token:
        return None
    try:
        import plivo
    except ImportError:
        logger.warning("plivo package not installed — phone tools unavailable")
        return None
    return plivo.RestClient(auth_id, auth_token)


def _get_from_number() -> str:
    return os.getenv("PLIVO_PHONE_NUMBER", "")


# ── Make Call ──────────────────────────────────────────────


class MakeCall(Tool):
    def __init__(self):
        super().__init__(
            name="make_call",
            description=(
                "Make an outbound phone call via Plivo. Supports Nigerian numbers (+234) "
                "and 200+ countries. Free trial: $10 credit. The callee hears a generic greeting."
            ),
            parameters={
                "to": {
                    "type": "string",
                    "description": "Phone number in E.164 format (e.g. +2349120500686, +14155551234)",
                    "required": True,
                },
            },
            permission="destructive",
        )

    def execute(self, **kwargs) -> str:
        client = _get_client()
        if not client:
            return (
                "Error: Plivo credentials not set.\n"
                "Get free credentials at https://console.plivo.com\n"
                "Then add to .env:\n"
                "  PLIVO_AUTH_ID=...\n"
                "  PLIVO_AUTH_TOKEN=...\n"
                "  PLIVO_PHONE_NUMBER=+..."
            )

        from_number = _get_from_number()
        if not from_number:
            return "Error: PLIVO_PHONE_NUMBER not set in .env"

        to_number = kwargs.get("to", "")
        if not to_number:
            return "Error: 'to' phone number is required (e.g. +2349120500686)"

        try:
            response = client.calls.create(
                from_=from_number,
                to_=to_number,
                answer_url=ANSWER_URL,
                answer_method="GET",
            )

            message_uuid = response.get("message", "")
            request_uuid = response.get("request_uuid", "")

            return (
                f"Call initiated!\n\n"
                f"Message: {message_uuid}\n"
                f"Request UUID: {request_uuid}\n"
                f"To: {to_number}\n"
                f"From: {from_number}\n\n"
                f"Use get_call_status to check progress."
            )

        except Exception as e:
            error_msg = str(e)
            if "not a valid" in error_msg.lower() or "unverified" in error_msg.lower():
                return (
                    f"Error: {error_msg}\n\n"
                    "With a Plivo trial account, you must verify the number first:\n"
                    "1. Go to https://console.plivo.com/account/verification\n"
                    f"2. Verify {to_number}\n"
                    "3. Then try again"
                )
            return f"Error making call: {e}"


# ── Get Call Status ────────────────────────────────────────


class GetCallStatus(Tool):
    def __init__(self):
        super().__init__(
            name="get_call_status",
            description="Check status of a phone call. Returns call UUID, status, duration.",
            parameters={
                "call_uuid": {
                    "type": "string",
                    "description": "The call UUID returned by make_call",
                    "required": True,
                },
            },
            permission="read_only",
        )

    def execute(self, **kwargs) -> str:
        client = _get_client()
        if not client:
            return "Error: Plivo credentials not set."

        call_uuid = kwargs.get("call_uuid", "")
        if not call_uuid:
            return "Error: 'call_uuid' is required."

        try:
            response = client.calls.get(call_uuid)
            result = response.get("objects", response)

            if isinstance(result, dict):
                status = result.get("call_status", result.get("status", "unknown"))
                return (
                    f"Call UUID: {call_uuid}\n"
                    f"Status: {status}\n"
                    f"From: {result.get('from', '?')}\n"
                    f"To: {result.get('to', '?')}\n"
                    f"Duration: {result.get('duration', '?')}s\n"
                    f"Direction: {result.get('direction', '?')}"
                )

            return f"Call UUID: {call_uuid}\nResponse: {result}"

        except Exception as e:
            return f"Error: {e}"


# ── Hangup ─────────────────────────────────────────────────


class HangupCall(Tool):
    def __init__(self):
        super().__init__(
            name="hangup_call",
            description="End an active phone call.",
            parameters={
                "call_uuid": {
                    "type": "string",
                    "description": "The call UUID to hang up",
                    "required": True,
                },
            },
            permission="destructive",
        )

    def execute(self, **kwargs) -> str:
        client = _get_client()
        if not client:
            return "Error: Plivo credentials not set."

        call_uuid = kwargs.get("call_uuid", "")
        if not call_uuid:
            return "Error: 'call_uuid' is required."

        try:
            response = client.calls.hangup(call_uuid)
            return f"Call {call_uuid} ended. Response: {response}"

        except Exception as e:
            return f"Error: {e}"


# ── List Calls ─────────────────────────────────────────────


class ListCalls(Tool):
    def __init__(self):
        super().__init__(
            name="list_calls",
            description="List recent phone calls with statuses and durations.",
            parameters={
                "limit": {
                    "type": "integer",
                    "description": "Number of calls to return (default 10)",
                },
            },
            permission="read_only",
        )

    def execute(self, **kwargs) -> str:
        client = _get_client()
        if not client:
            return "Error: Plivo credentials not set."

        limit = kwargs.get("limit", 10)

        try:
            response = client.calls.list(limit=limit)
            calls = response.get("objects", [])

            if not calls:
                return "No calls found."

            lines = []
            for call in calls:
                call_uuid = call.get("call_uuid", "?")
                to_num = call.get("to", "?")
                status = call.get("call_status", "?")
                duration = call.get("duration", "?")
                lines.append(f"[{status}] {to_num} — {duration}s (UUID: {call_uuid})")

            return "\n".join(lines)

        except Exception as e:
            return f"Error: {e}"


# ── Register ───────────────────────────────────────────────


def register():
    """Register all phone tools."""
    for tool_cls in (MakeCall, GetCallStatus, HangupCall, ListCalls):
        registry.register(tool_cls())
