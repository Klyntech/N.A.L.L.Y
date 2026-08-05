"""Tests for SubAgent model override — model flows from planner to LLM call."""

from nally.config import SUBAGENT_MODELS
from nally.subagent.agent import SubAgent
from nally.subagent.pool import SubAgentPool


def test_subagent_stores_model():
    agent = SubAgent(goal="test", model="deepseek-v4-flash-free")
    assert agent.model == "deepseek-v4-flash-free"


def test_subagent_default_model_is_none():
    agent = SubAgent(goal="test")
    assert agent.model is None


def test_pool_passes_model_to_agent():
    pool = SubAgentPool()
    agent_id = pool.spawn(goal="test", model="nemotron-3-ultra-free")
    agent = pool._agents.get(agent_id)
    assert agent is not None
    assert agent.model == "nemotron-3-ultra-free"
    pool.clear()


def test_pool_default_model_is_none():
    pool = SubAgentPool()
    agent_id = pool.spawn(goal="test")
    agent = pool._agents.get(agent_id)
    assert agent is not None
    assert agent.model is None
    pool.clear()


def test_pool_spawn_many_passes_model():
    pool = SubAgentPool()
    tasks = [{"goal": "task1"}, {"goal": "task2"}]
    ids = pool.spawn_many(tasks, model="ling-3.0-flash-free")
    for aid in ids:
        agent = pool._agents.get(aid)
        assert agent is not None
        assert agent.model == "ling-3.0-flash-free"
    pool.clear()


def test_subagent_models_config_not_empty():
    assert len(SUBAGENT_MODELS) > 0


def test_subagent_models_are_strings():
    for m in SUBAGENT_MODELS:
        assert isinstance(m, str)
        assert "-free" in m


def test_no_gpt_in_subagent_models():
    for m in SUBAGENT_MODELS:
        assert "gpt" not in m.lower()


def test_model_in_agent_get_status():
    agent = SubAgent(goal="test", model="laguna-s-2.1-free")
    status = agent.get_status()
    assert status["id"] == agent.id


def test_model_in_agent_to_dict():
    agent = SubAgent(goal="test", model="mimo-v2.5-free")
    d = agent.to_dict()
    assert d["goal"] == "test"
