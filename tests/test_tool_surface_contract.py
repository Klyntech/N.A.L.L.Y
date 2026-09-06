"""Tool-surface contract: one entry point, one execution boundary.

Locks the post-consolidation invariant:
  Every model-invoked capability has exactly one model-facing entry point
  (its registry name) and exactly one authoritative runtime execution
  boundary (ToolRegistry.execute_result). Framework-internal state
  operations (memory/history/task-state bookkeeping) legitimately bypass
  the model-tool boundary.

1. Surface snapshot: registry names after load_all_tools() == expected set.
2. Boundary: the auto-search path routes through registry.execute_result
   (no direct WebSearch().execute()).
3. Policy coverage: every registered non-mcp_* tool has an explicit
   permissions.json key or is in the documented DEFAULT_ASK set.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from nally.tools import load_all_tools
from nally.tools.registry import registry
from nally.tools.result import ToolResult

EXPECTED_SURFACE = sorted(
    [
        # execution (3)
        "run_command",
        "run_code",
        "code_analysis",
        # files (2)
        "read_file",
        "file_ops",
        # web (2)
        "web_search",
        "fetch",
        # design (1)
        "web_design",
        # state (1)
        "task_state",
        # image/vision (3)
        "generate_image",
        "analyze_image",
        "edit_image",
        # email (2)
        "gmail_read",
        "gmail_write",
        # memory (1)
        "memory",
        # delegation (2)
        "agent",
        "engineering_build",
        # reasoning (1)
        "think",
        # observability (1)
        "system_health",
    ]
)

# Live tools with no permissions.json key: unknown tools default to ASK
# (permissions.py). This set is explicit so adding a key or a tool forces
# a deliberate update here — no more silent ASK.
DEFAULT_ASK = sorted(
    [
        "fetch",
        "web_design",
        "task_state",
        "analyze_image",
        "edit_image",
    ]
)


def _repo_root() -> Path:
    return Path(__file__).parent.parent


class TestSurfaceSnapshot:
    def test_registry_surface_matches_expected(self):
        load_all_tools()
        assert sorted(registry.tools.keys()) == EXPECTED_SURFACE

    def test_removed_names_absent(self):
        load_all_tools()
        for name in (
            "make_call",
            "get_call_status",
            "hangup_call",
            "list_calls",
            "bridge_execute",
            "shell_sessions",
            "shell_output",
            "shell_stdin",
        ):
            assert name not in registry.tools


class TestExecutionBoundary:
    def test_auto_search_routes_through_registry(self, monkeypatch):
        """core._llm_process auto-search must use registry.execute_result."""
        from nally.agent import core as core_mod

        store = MagicMock()
        store.get_user_facts.return_value = "No user facts stored yet."
        store.get_conversation_summaries_text.return_value = ""
        store.get_recent_episodes_text.return_value = ""
        store.load_messages.return_value = []
        monkeypatch.setattr(core_mod, "memory_store", store)

        mgr = MagicMock()
        mgr.prune.side_effect = lambda messages, **kw: messages
        mgr.compact.side_effect = lambda messages, **kw: messages
        mgr.inject_memories.side_effect = lambda query, messages: messages
        mgr.inject_conversation_history.side_effect = lambda messages: messages
        mgr.estimate_tokens.return_value = 0

        agent = core_mod.NallyAgent(session_id="test-surface-boundary")
        with (
            patch("nally.agent.llm.llm") as mock_llm,
            patch("nally.agent.context.context_manager", mgr),
            patch("nally.tools.registry.registry") as mock_registry,
            patch("nally.agent.graph.run_agent", return_value="BOUNDARY DONE"),
        ):
            mock_llm.simple_chat.side_effect = Exception("no network in contract tests")
            mock_registry.execute_result.return_value = ToolResult.success(
                value="search-result-stub"
            )
            result = agent.process("latest score update")

        assert result == "BOUNDARY DONE"
        mock_registry.execute_result.assert_called_once()
        name, args = mock_registry.execute_result.call_args.args
        assert name == "web_search"
        assert args["query"] == "latest score update"

    def test_no_direct_tool_instantiation_in_agent_core(self):
        """The agent brain must not construct tool classes directly."""
        import nally.agent.core as core_mod

        src = Path(core_mod.__file__).read_text(encoding="utf-8")
        assert "WebSearch()" not in src


class TestPolicyCoverage:
    def test_every_tool_has_explicit_key_or_default_ask(self):
        load_all_tools()
        perms = json.loads(
            (_repo_root() / "nally" / "config" / "permissions.json").read_text(
                encoding="utf-8"
            )
        )
        uncovered = [
            name
            for name in registry.tools
            if not name.startswith("mcp_") and name not in perms and name not in DEFAULT_ASK
        ]
        assert uncovered == [], f"tools with neither key nor documented default: {uncovered}"

    def test_default_ask_set_is_exact(self):
        """DEFAULT_ASK must not silently grow or shrink."""
        load_all_tools()
        perms = json.loads(
            (_repo_root() / "nally" / "config" / "permissions.json").read_text(
                encoding="utf-8"
            )
        )
        actual_unkeyed = sorted(
            name
            for name in registry.tools
            if not name.startswith("mcp_") and name not in perms
        )
        assert actual_unkeyed == DEFAULT_ASK
