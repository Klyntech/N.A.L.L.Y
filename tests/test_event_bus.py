"""Tests for nally.events.bus — event bus pub/sub."""

import threading
import time

from nally.events.bus import Event, EventBus


def test_publish_subscribe():
    bus = EventBus()
    received = []

    def handler(event):
        received.append(event)

    bus.subscribe("test_event", handler)
    bus.publish("test_event", {"value": 42})

    assert len(received) == 1
    assert received[0].data == {"value": 42}
    assert received[0].type == "test_event"


def test_multiple_subscribers():
    bus = EventBus()
    results_a = []
    results_b = []

    bus.subscribe("evt", lambda e: results_a.append(e))
    bus.subscribe("evt", lambda e: results_b.append(e))
    bus.publish("evt", {"x": 1})

    assert len(results_a) == 1
    assert len(results_b) == 1


def test_unsubscribe():
    bus = EventBus()
    received = []

    unsub = bus.subscribe("evt", lambda e: received.append(e))
    bus.publish("evt", {"x": 1})
    assert len(received) == 1

    unsub()
    bus.publish("evt", {"x": 2})
    assert len(received) == 1  # No new event


def test_wrong_event_not_received():
    bus = EventBus()
    received = []

    bus.subscribe("event_a", lambda e: received.append(e))
    bus.publish("event_b", {"x": 1})

    assert len(received) == 0


def test_history_ring_buffer():
    bus = EventBus()
    bus.publish("evt", {"i": 0})
    bus.publish("evt", {"i": 1})
    bus.publish("evt", {"i": 2})

    history = bus.get_history("evt", limit=2)
    assert len(history) == 2
    assert history[0].data == {"i": 1}
    assert history[1].data == {"i": 2}


def test_thread_safety():
    bus = EventBus()
    received = []
    lock = threading.Lock()

    def handler(event):
        with lock:
            received.append(event)

    bus.subscribe("concurrent", handler)

    threads = []
    for i in range(20):
        t = threading.Thread(target=lambda i=i: bus.publish("concurrent", {"i": i}))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    assert len(received) == 20


def test_subscribe_returns_callable():
    bus = EventBus()
    result = bus.subscribe("evt", lambda e: None)
    assert callable(result)
