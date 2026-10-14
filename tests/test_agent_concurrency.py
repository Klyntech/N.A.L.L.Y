"""Regression tests for serializing concurrent turns on one agent."""

import importlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

core = importlib.import_module("nally.agent.core")


def test_process_serializes_turns_for_shared_agent(monkeypatch):
    agent = object.__new__(core.NallyAgent)
    agent._lock = threading.Lock()
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def fake_process(text, emit=None):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.03)
        with state_lock:
            active -= 1
        return text

    monkeypatch.setattr(agent, "_llm_process", fake_process)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(agent.process, ["first", "second"]))

    assert results == ["first", "second"]
    assert maximum_active == 1
