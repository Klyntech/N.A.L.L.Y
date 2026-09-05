"""WebSocket connection owns agent/voice tasks; disconnect cancels them."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest


def _import_ws_helpers():
    if "fastapi" not in sys.modules:
        sys.modules["fastapi"] = types.ModuleType("fastapi")
        sys.modules["fastapi"].WebSocket = type("WebSocket", (), {})
        sys.modules["fastapi"].WebSocketDisconnect = type(
            "WebSocketDisconnect", (Exception,), {}
        )
    if "nally.web" not in sys.modules:
        pkg = types.ModuleType("nally.web")
        pkg.__path__ = [str(__import__("pathlib").Path("nally/web").resolve())]
        sys.modules["nally.web"] = pkg
    import nally.web.ws_handler as mod

    return mod._cancel_connection_tasks, mod._track_connection_task


_cancel_connection_tasks, _track_connection_task = _import_ws_helpers()


def test_completed_task_removed_from_tracking():
    async def _run():
        in_flight: set = set()

        async def work():
            return "ok"

        t = _track_connection_task(in_flight, work())
        assert t in in_flight
        await t
        await asyncio.sleep(0)
        assert t not in in_flight

    asyncio.run(_run())


def test_multiple_tasks_tracked():
    async def _run():
        in_flight: set = set()
        gates = [asyncio.Event(), asyncio.Event()]

        async def hold(i):
            await gates[i].wait()

        t0 = _track_connection_task(in_flight, hold(0))
        t1 = _track_connection_task(in_flight, hold(1))
        assert in_flight == {t0, t1}
        gates[0].set()
        gates[1].set()
        await asyncio.gather(t0, t1)
        await asyncio.sleep(0)
        assert in_flight == set()

    asyncio.run(_run())


def test_cancel_all_in_flight_on_cleanup():
    async def _run():
        in_flight: set = set()
        started = asyncio.Event()
        cancelled = {"n": 0}

        async def hang():
            started.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancelled["n"] += 1
                raise

        t0 = _track_connection_task(in_flight, hang())
        t1 = _track_connection_task(in_flight, hang())
        await started.wait()

        async def heartbeat():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancelled["n"] += 1
                raise

        hb = asyncio.create_task(heartbeat())
        await _cancel_connection_tasks(in_flight, hb, route_key="web:test-route")
        assert cancelled["n"] >= 2
        assert t0.cancelled() or t0.done()
        assert t1.cancelled() or t1.done()
        assert hb.cancelled() or hb.done()
        assert in_flight == set()

    asyncio.run(_run())


def test_completed_tasks_not_cancelled_during_cleanup():
    async def _run():
        in_flight: set = set()

        async def quick():
            return 1

        t = _track_connection_task(in_flight, quick())
        await t
        await asyncio.sleep(0)
        assert t not in in_flight

        await _cancel_connection_tasks(in_flight, None, route_key="web:x")
        assert t.done()
        assert not t.cancelled()
        assert t.result() == 1

    asyncio.run(_run())


def test_failing_task_does_not_break_cleanup():
    async def _run():
        in_flight: set = set()

        async def boom():
            raise RuntimeError("agent failed")

        t = _track_connection_task(in_flight, boom())
        with pytest.raises(RuntimeError):
            await t
        await asyncio.sleep(0)

        async def hang():
            await asyncio.sleep(3600)

        hang_t = _track_connection_task(in_flight, hang())
        await _cancel_connection_tasks(in_flight, None, route_key="web:y")
        assert hang_t.cancelled() or hang_t.done()

    asyncio.run(_run())


def test_abort_signaled_for_route():
    async def _run():
        from nally.core import abort as abort_mod

        abort_mod.clear_abort("web:abort-route")
        in_flight: set = set()

        async def hang():
            await asyncio.sleep(3600)

        _track_connection_task(in_flight, hang())
        await _cancel_connection_tasks(in_flight, None, route_key="web:abort-route")
        assert abort_mod.check_abort("web:abort-route") is True
        abort_mod.clear_abort("web:abort-route")

    asyncio.run(_run())


def test_heartbeat_cancelled_with_inflight():
    async def _run():
        in_flight: set = set()
        flags = {"hb": False, "msg": False}

        async def hb():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                flags["hb"] = True
                raise

        async def msg():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                flags["msg"] = True
                raise

        heartbeat = asyncio.create_task(hb())
        msg_t = _track_connection_task(in_flight, msg())
        # Let both enter sleep so CancelledError handlers run
        await asyncio.sleep(0.01)
        await _cancel_connection_tasks(in_flight, heartbeat, route_key="web:z")
        assert heartbeat.cancelled() or heartbeat.done()
        assert msg_t.cancelled() or msg_t.done()
        assert flags["msg"] is True

    asyncio.run(_run())
