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


def test_bridge_result_cannot_resolve_another_devices_request():
    async def scenario():
        registry = BridgeRegistry()
        device_a = registry.register("device-a", MagicMock(), "test", [])
        device_b = registry.register("device-b", MagicMock(), "test", [])
        future = asyncio.get_running_loop().create_future()
        registry._pending["secret-request"] = (device_a, future)

        registry.resolve_result("secret-request", "forged", True, device=device_b)
        assert not future.done()

        registry.resolve_result("secret-request", "valid", True, device=device_a)
        assert future.result() == ("valid", True)

    asyncio.run(scenario())


def test_stale_connection_cleanup_does_not_remove_reconnected_device():
    registry = BridgeRegistry()
    old_device = registry.register("same-id", MagicMock(), "old", [])
    new_device = registry.register("same-id", MagicMock(), "new", [])

    registry.unregister("same-id", expected_device=old_device)

    assert registry.get_device("same-id") is new_device


def test_unregister_only_resolves_requests_for_disconnected_device():
    async def scenario():
        registry = BridgeRegistry()
        loop = asyncio.get_running_loop()
        device_a = registry.register("device-a", MagicMock(), "test", [])
        device_b = registry.register("device-b", MagicMock(), "test", [])
        a = loop.create_future()
        b = loop.create_future()
        registry._pending["request-a"] = (device_a, a)
        registry._pending["request-b"] = (device_b, b)

        registry.unregister("device-a")

        assert a.done()
        assert not a.cancelled()
        assert a.result() == ("Error: Bridge device disconnected: device-a", False)
        assert not b.done()
        assert "request-a" not in registry._pending
        assert registry._pending["request-b"] == (device_b, b)

        b.cancel()

    asyncio.run(scenario())
