"""T4: skill advertised-but-unresolvable tools fail at activation."""

from unittest.mock import MagicMock, patch

from nally.tools.registry import Tool, registry
from nally.tools.filter import tool_filter


def _stubbed_agent(monkeypatch):
    import nally.agent.core as core_mod

    store = MagicMock()
    store.get_user_facts.return_value = "No user facts stored yet."
    store.get_conversation_summaries_text.return_value = ""
    store.get_recent_episodes_text.return_value = ""
    store.load_messages.return_value = []
    monkeypatch.setattr(core_mod, "memory_store", store)
    return core_mod


def test_mismatch_skips_invalid_and_injects_notice(monkeypatch):
    from nally.skills.loader import Skill

    core_mod = _stubbed_agent(monkeypatch)

    from nally.tools import load_all_tools

    load_all_tools()
    tool_filter.build_index(registry.tools)
    assert registry.get("read_file") is not None
    assert registry.get("mcp_higgsfield_generate_video") is None

    fake_skill = Skill(
        name="video-edit",
        description="video edit skill",
        body="do video stuff",
        allowed_tools=["read_file", "mcp_higgsfield_generate_video", "mcp_higgsfield_generate_image"],
        source_path=MagicMock(),
    )

    fake_registry = MagicMock()
    fake_registry._loaded = True
    fake_registry.find_by_intent.return_value = ["video-edit"]
    fake_registry.get.return_value = fake_skill
    fake_registry.activate.return_value = fake_skill.body
    fake_registry.manifest = ""
    monkeypatch.setattr("nally.skills.registry.skill_registry", fake_registry)

    agent = core_mod.NallyAgent(session_id="test-skill-mismatch")
    agent.messages = [{"role": "system", "content": "sys"}]

    with patch("nally.tools.permissions.gate.set_skill_overrides") as mock_set:
        with patch("nally.agent.graph.run_agent", return_value="ok"):
            with patch("nally.agent.harness.classify_intent") as mock_classify:
                from nally.agent.harness import Classification, TaskClass

                mock_classify.return_value = Classification(
                    task_class=TaskClass.SIMPLE, confidence=0.9, reasoning="test", method="test"
                )
                agent.process("do video edit please")

        assert any("SKILL TOOL MISMATCH" in m.get("content", "") for m in agent.messages)
        assert any("mcp_higgsfield_generate_video" in m.get("content", "") for m in agent.messages)
        mock_set.assert_called_once()
        args = mock_set.call_args[0]
        assert args[0] == "video-edit"
        assert "read_file" in args[1]
        assert "mcp_higgsfield_generate_video" not in args[1]


def test_all_valid_no_mismatch_injected(monkeypatch):
    from nally.skills.loader import Skill

    core_mod = _stubbed_agent(monkeypatch)
    from nally.tools import load_all_tools

    load_all_tools()
    fake_skill = Skill(
        name="test-skill",
        description="test",
        body="body",
        allowed_tools=["read_file", "file_ops"],
        source_path=MagicMock(),
    )
    fake_registry = MagicMock()
    fake_registry._loaded = True
    fake_registry.find_by_intent.return_value = ["test-skill"]
    fake_registry.get.return_value = fake_skill
    fake_registry.activate.return_value = fake_skill.body
    fake_registry.manifest = ""
    monkeypatch.setattr("nally.skills.registry.skill_registry", fake_registry)

    agent = core_mod.NallyAgent(session_id="test-skill-valid")
    agent.messages = [{"role": "system", "content": "sys"}]
    with patch("nally.tools.permissions.gate.set_skill_overrides") as mock_set:
        with patch("nally.agent.graph.run_agent", return_value="ok"):
            with patch("nally.agent.harness.classify_intent") as mock_classify:
                from nally.agent.harness import Classification, TaskClass

                mock_classify.return_value = Classification(
                    task_class=TaskClass.SIMPLE, confidence=0.9, reasoning="test", method="test"
                )
                agent.process("test valid skill")

        assert not any("SKILL TOOL MISMATCH" in m.get("content", "") for m in agent.messages)
        mock_set.assert_called_once_with("test-skill", ["read_file", "file_ops"])
