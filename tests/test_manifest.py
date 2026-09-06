"""T1: capability manifest is a generated projection of the registry."""

from unittest.mock import MagicMock

from nally.tools.manifest import _first_line, get_capability_manifest


def _fake_registry(names_descriptions):
    registry = MagicMock()
    tools = {}
    for name, desc in names_descriptions.items():
        tool = MagicMock()
        tool.name = name
        tool.description = desc
        tools[name] = tool
    registry.tools = tools
    return registry


class TestManifestGeneration:
    def test_lists_every_registered_tool(self):
        registry = _fake_registry({"b_tool": "Does B.", "a_tool": "Does A."})
        manifest = get_capability_manifest(registry)
        assert "- a_tool: Does A." in manifest
        assert "- b_tool: Does B." in manifest

    def test_sorted_by_name(self):
        registry = _fake_registry({"z": "Z.", "a": "A.", "m": "M."})
        lines = get_capability_manifest(registry).splitlines()[1:]
        assert [line.split(":")[0] for line in lines] == ["- a", "- m", "- z"]

    def test_no_schemas_or_counts(self):
        registry = _fake_registry({"run_command": "Execute commands."})
        manifest = get_capability_manifest(registry)
        assert "parameters" not in manifest
        assert "run_command" in manifest

    def test_multiline_description_uses_first_line(self):
        registry = _fake_registry({"t": "First line.\nSecond line."})
        assert "- t: First line." in get_capability_manifest(registry)

    def test_long_description_truncated(self):
        registry = _fake_registry({"t": "word " * 100})
        line = get_capability_manifest(registry).splitlines()[1]
        assert len(line) < 200
        assert line.endswith("...")

    def test_missing_description_tolerated(self):
        registry = _fake_registry({"t": ""})
        assert "- t: (no description)" in get_capability_manifest(registry)

    def test_broken_registry_returns_empty(self):
        broken = MagicMock()
        type(broken).tools = property(lambda self: (_ for _ in ()).throw(Exception("db down")))
        assert get_capability_manifest(broken) == ""

    def test_first_line_helper(self):
        assert _first_line("") == "(no description)"
        assert _first_line("  spaced  ") == "spaced"


class TestManifestLiveRegistry:
    def test_matches_registry_keys(self):
        from nally.tools import load_all_tools
        from nally.tools.registry import registry

        load_all_tools()
        manifest = get_capability_manifest()
        for name in registry.tools:
            assert f"- {name}:" in manifest
