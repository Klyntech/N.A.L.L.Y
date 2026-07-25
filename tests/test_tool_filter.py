"""Tests for nally.tools.filter.ToolFilter — keyword-based tool selection."""
import pytest
from nally.tools import load_all_tools, registry
from nally.tools.filter import tool_filter


@pytest.fixture(scope="module", autouse=True)
def _build_index():
    """Load tools and build the filter index once for all tests."""
    load_all_tools()
    tool_filter.build_index(registry.tools)


def test_generic_query_returns_all_tools():
    """Generic queries with no strong keyword matches return the full tool set."""
    result = tool_filter.select("hello how are you")
    names = {t["function"]["name"] for t in result}
    assert len(result) == len(registry.tools)
    assert names == set(registry.tools.keys())


def test_specific_query_narrows_correctly():
    """File-specific query includes read_file and excludes clearly unrelated tools."""
    result = tool_filter.select("read the contents of a file on disk")
    names = {t["function"]["name"] for t in result}
    assert "read_file" in names
    assert "agent" not in names
    assert "forget" not in names


def test_empty_query_returns_all_tools():
    """Empty string gracefully returns the full tool set."""
    result = tool_filter.select("")
    assert len(result) == len(registry.tools)


def test_deterministic_output():
    """Same query always produces the same tool list (cache stability)."""
    q = "run python code to analyze data"
    first = tool_filter.select(q)
    second = tool_filter.select(q)
    assert first == second
