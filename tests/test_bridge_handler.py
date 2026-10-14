"""Regression tests for NallyBridge authentication and request cleanup."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from nally.web.bridge_handler import BridgeRegistry, bridge_websocket


def test_bridge_auth_missing_token_closes_connection(monkeypatch):
    monkeypatch.delenv("NALLY_BRIDGE_TOKEN", raising=False)
    websocket = MagicMock()
    websocket.query_params.get.return_value = "anything"
    websocket.close = AsyncMock()

    asyncio.run(bridge_websocket(websocket, "test-device"))

    websocket.close.assert_awaited_once_with(code=4001, reason="Unauthorized")
    websocket.accept.assert_not_called()


def test_unregister_only_cancels_requests_for_disconnected_device():
    async def scenario():
        registry = BridgeRegistry()
        loop = asyncio.get_running_loop()
        a = loop.create_future()
        b = loop.create_future()
        registry._pending["request-a"] = ("device-a", a)
        registry._pending["request-b"] = ("device-b", b)

        registry.unregister("device-a")

        assert a.done()
        assert not a.cancelled()
        assert a.result() == ("Error: Bridge device disconnected: device-a", False)
        assert not b.done()
        assert "request-a" not in registry._pending
        assert registry._pending["request-b"] == ("device-b", b)

        b.cancel()

    asyncio.run(scenario())
