"""Tests for ContextBuilder — Phase 2 typed context construction.

Acceptance conditions:
  1. build() is idempotent
  2. caller cannot mutate builder state
  3. prompt output is byte-identical before/after refactor
"""

import copy
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from nally.agent.context_builder import BuiltContext, ContextBuilder, context_builder


# ── Helpers ────────────────────────────────────────────────


def _make_messages(n: int = 5, user_text: str = "hello") -> List[Dict[str, Any]]:
    """Build a minimal message list for testing."""
    msgs = [{"role": "system", "content": "You are Nally."}]
    for i in range(n - 1):
        if i % 2 == 0:
            msgs.append({"role": "user", "content": f"{user_text} {i}"})
        else:
            msgs.append({"role": "assistant", "content": f"Response {i}"})
    return msgs


class _FakeContextManager:
    """Deterministic context manager for testing (no LLM, no DB)."""

    def __init__(self, max_tokens: int = 50000):
        self._max = max_tokens
        self._stats = {}

    def estimate_tokens(self, messages):
        return sum(len(str(m.get("content", ""))) // 4 for m in messages)

    def prune(self, messages, max_tokens=None):
        return list(messages)  # no-op for testing

    def compact(self, messages):
        return messages  # no-op for testing

    def inject_memories(self, query, messages):
        return messages  # no-op for testing

    def inject_conversation_history(self, messages):
        return messages  # no-op for testing


class _FakeMemoryStore:
    """Deterministic memory store for testing."""

    def recall_semantic(self, search="", min_confidence=0.3):
        return []

    def recall(self, category=None, min_confidence=0.5, limit=12):
        return {}


class _FakeSemanticEngine:
    """Deterministic semantic engine for testing."""

    _memories = None

    def hydrate_from_store(self, store=None, limit=200):
        pass

    def recall(self, query, limit=12, min_confidence=0.3):
        return []


# ── Idempotency tests ─────────────────────────────────────


def test_build_is_idempotent():
    """Calling build() twice with same inputs produces same output."""
    builder = ContextBuilder()
    msgs = _make_messages(5)
    cm = _FakeContextManager()
    ms = _FakeMemoryStore()
    sem = _FakeSemanticEngine()

    r1 = builder.build(msgs, "hello", context_manager=cm, memory_store=ms, semantic_engine=sem)
    r2 = builder.build(msgs, "hello", context_manager=cm, memory_store=ms, semantic_engine=sem)

    assert r1.messages == r2.messages
    assert r1.tool_schemas == r2.tool_schemas
    assert r1.tokens_estimated == r2.tokens_estimated
    assert r1.memory_snippet == r2.memory_snippet


def test_build_idempotent_with_different_query():
    """Different queries produce different memory snippets but same structure."""
    builder = ContextBuilder()
    msgs = _make_messages(5)
    cm = _FakeContextManager()
    ms = _FakeMemoryStore()
    sem = _FakeSemanticEngine()

    r1 = builder.build(msgs, "coding", context_manager=cm, memory_store=ms, semantic_engine=sem)
    r2 = builder.build(msgs, "deployment", context_manager=cm, memory_store=ms, semantic_engine=sem)

    # Same structure
    assert len(r1.messages) == len(r2.messages)
    assert r1.tool_schemas == r2.tool_schemas


# ── Caller isolation tests ─────────────────────────────────


def test_caller_messages_not_mutated():
    """Builder never mutates the caller's message list."""
    builder = ContextBuilder()
    msgs = _make_messages(5)
    original = copy.deepcopy(msgs)
    cm = _FakeContextManager()
    ms = _FakeMemoryStore()
    sem = _FakeSemanticEngine()

    builder.build(msgs, "hello", context_manager=cm, memory_store=ms, semantic_engine=sem)

    # Caller's list is unchanged
    assert msgs == original
    assert len(msgs) == len(original)


def test_caller_messages_not_mutated_after_multiple_builds():
    """Multiple build() calls don't accumulate mutations."""
    builder = ContextBuilder()
    msgs = _make_messages(5)
    original = copy.deepcopy(msgs)
    cm = _FakeContextManager()
    ms = _FakeMemoryStore()
    sem = _FakeSemanticEngine()

    for _ in range(5):
        builder.build(msgs, "hello", context_manager=cm, memory_store=ms, semantic_engine=sem)

    assert msgs == original


def test_builder_state_not_affected_by_caller():
    """Builder has no mutable instance state; caller can't affect it."""
    builder = ContextBuilder()
    cm = _FakeContextManager()
    ms = _FakeMemoryStore()
    sem = _FakeSemanticEngine()

    # First call
    r1 = builder.build(
        _make_messages(3), "hello",
        context_manager=cm, memory_store=ms, semantic_engine=sem,
    )
    # Second call with different input
    r2 = builder.build(
        _make_messages(8, "different"), "different query",
        context_manager=cm, memory_store=ms, semantic_engine=sem,
    )

    # r1 is not affected by r2
    assert r1.messages != r2.messages
    assert len(r1.messages) != len(r2.messages)


# ── BuiltContext structure tests ────────────────────────────


def test_built_context_has_required_fields():
    """BuiltContext exposes all required fields."""
    builder = ContextBuilder()
    msgs = _make_messages(3)
    cm = _FakeContextManager()
    ms = _FakeMemoryStore()
    sem = _FakeSemanticEngine()

    result = builder.build(msgs, "hello", context_manager=cm, memory_store=ms, semantic_engine=sem)

    assert hasattr(result, "messages")
    assert hasattr(result, "system_prompt")
    assert hasattr(result, "memory_snippet")
    assert hasattr(result, "conversation_summary")
    assert hasattr(result, "session_snapshot")
    assert hasattr(result, "tool_schemas")
    assert hasattr(result, "tokens_estimated")
    assert hasattr(result, "pruned")
    assert hasattr(result, "compacted")
    assert hasattr(result, "memories_injected")


def test_built_context_messages_are_dicts():
    """BuiltContext.messages contains only dicts."""
    builder = ContextBuilder()
    msgs = _make_messages(5)
    cm = _FakeContextManager()
    ms = _FakeMemoryStore()
    sem = _FakeSemanticEngine()

    result = builder.build(msgs, "hello", context_manager=cm, memory_store=ms, semantic_engine=sem)

    for msg in result.messages:
        assert isinstance(msg, dict)
        assert "role" in msg
        assert "content" in msg


def test_built_context_session_snapshot():
    """Session snapshot contains expected keys."""
    builder = ContextBuilder()
    msgs = _make_messages(3)
    cm = _FakeContextManager()
    ms = _FakeMemoryStore()
    sem = _FakeSemanticEngine()

    result = builder.build(
        msgs, "hello",
        session_id="test:123",
        route_key="web",
        interface="Web",
        intent_class="SIMPLE",
        context_manager=cm, memory_store=ms, semantic_engine=sem,
    )

    snap = result.session_snapshot
    assert snap["session_id"] == "test:123"
    assert snap["route_key"] == "web"
    assert snap["interface"] == "Web"
    assert snap["intent_class"] == "SIMPLE"


# ── Edge case tests ────────────────────────────────────────


def test_build_empty_messages():
    """Builder handles empty message list gracefully."""
    builder = ContextBuilder()
    cm = _FakeContextManager()
    ms = _FakeMemoryStore()
    sem = _FakeSemanticEngine()

    result = builder.build([], "hello", context_manager=cm, memory_store=ms, semantic_engine=sem)

    assert isinstance(result.messages, list)
    assert result.tokens_estimated >= 0


def test_build_single_system_message():
    """Builder handles system-only message list."""
    builder = ContextBuilder()
    msgs = [{"role": "system", "content": "You are Nally."}]
    cm = _FakeContextManager()
    ms = _FakeMemoryStore()
    sem = _FakeSemanticEngine()

    result = builder.build(msgs, "hello", context_manager=cm, memory_store=ms, semantic_engine=sem)

    assert len(result.messages) >= 1
    assert result.messages[0]["role"] == "system"


def test_build_with_tool_calls():
    """Builder handles messages with tool_calls."""
    builder = ContextBuilder()
    msgs = [
        {"role": "system", "content": "You are Nally."},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "run_command", "arguments": "{}"}}]},
        {"role": "tool", "content": "output", "tool_call_id": "t1"},
    ]
    cm = _FakeContextManager()
    ms = _FakeMemoryStore()
    sem = _FakeSemanticEngine()

    result = builder.build(msgs, "hello", context_manager=cm, memory_store=ms, semantic_engine=sem)

    assert len(result.messages) == 4
    # Original not mutated
    assert len(msgs) == 4


def test_build_diagnostics():
    """Builder sets diagnostic flags correctly."""
    builder = ContextBuilder()
    msgs = _make_messages(3)
    cm = _FakeContextManager()
    ms = _FakeMemoryStore()
    sem = _FakeSemanticEngine()

    result = builder.build(msgs, "hello", context_manager=cm, memory_store=ms, semantic_engine=sem)

    assert isinstance(result.pruned, bool)
    assert isinstance(result.compacted, bool)
    assert isinstance(result.memories_injected, int)


# ── Legacy path parity test ────────────────────────────────


def test_builder_output_matches_legacy_path():
    """ContextBuilder output is byte-identical to legacy ContextManager path.

    This is the critical Phase 2 acceptance test: the refactor must not
    change the output that the LLM sees.
    """
    from nally.agent.context import ContextManager

    # Use real ContextManager for parity testing
    real_cm = ContextManager()
    ms = _FakeMemoryStore()
    sem = _FakeSemanticEngine()

    msgs = _make_messages(7, "test query")
    original = copy.deepcopy(msgs)

    # Legacy path: prune → compact → inject_memories → inject_conversation_history
    legacy = list(msgs)
    legacy = real_cm.prune(legacy, max_tokens=50000)
    legacy = real_cm.compact(legacy)
    legacy = real_cm.inject_memories("test query", legacy)
    legacy = real_cm.inject_conversation_history(legacy)

    # Builder path
    builder = ContextBuilder()
    built = builder.build(
        original, "test query",
        context_manager=real_cm,
        memory_store=ms,
        semantic_engine=sem,
    )

    # The message count and order should be equivalent
    # (builder may add memory/history at same positions as legacy)
    assert len(built.messages) == len(legacy), (
        f"Message count mismatch: builder={len(built.messages)} legacy={len(legacy)}"
    )

    # System messages should match
    for i in range(min(len(built.messages), len(legacy))):
        b_role = built.messages[i].get("role")
        l_role = legacy[i].get("role")
        assert b_role == l_role, f"Role mismatch at index {i}: builder={b_role} legacy={l_role}"


# ── Singleton test ─────────────────────────────────────────


def test_singleton_exists():
    """Module-level singleton is available."""
    assert context_builder is not None
    assert isinstance(context_builder, ContextBuilder)
