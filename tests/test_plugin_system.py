"""Tests for plugin system hardening: allowlist + permission validation."""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from nally.tools.registry import VALID_PERMISSIONS, Tool, ToolRegistry


def test_valid_permissions_set():
    """VALID_PERMISSIONS contains all expected tiers."""
    assert "safe" in VALID_PERMISSIONS
    assert "destructive" in VALID_PERMISSIONS
    assert "write" in VALID_PERMISSIONS
    assert "read_only" in VALID_PERMISSIONS
    assert len(VALID_PERMISSIONS) == 4


def test_register_valid_permission():
    """Tool with valid permission registers successfully."""
    reg = ToolRegistry()
    tool = Tool(name="test_tool", description="test", permission="safe")
    reg.register(tool)
    assert "test_tool" in reg.tools


def test_register_all_valid_permissions():
    """All four valid permission tiers register without error."""
    reg = ToolRegistry()
    for perm in VALID_PERMISSIONS:
        tool = Tool(name=f"tool_{perm}", description="test", permission=perm)
        reg.register(tool)
    assert len(reg.tools) == 4


def test_register_invalid_permission_raises():
    """Tool with invalid permission raises ValueError."""
    reg = ToolRegistry()
    tool = Tool(name="bad_tool", description="test", permission="invalid")
    with pytest.raises(ValueError, match="invalid permission"):
        reg.register(tool)


def test_register_invalid_permission_does_not_store():
    """Failed validation doesn't leave partial state."""
    reg = ToolRegistry()
    tool = Tool(name="bad_tool", description="test", permission="hacked")
    try:
        reg.register(tool)
    except ValueError:
        pass
    assert "bad_tool" not in reg.tools


def test_plugin_allowlist_skips_unlisted():
    """Plugin not in allowlist is skipped."""
    tmpdir = Path(tempfile.mkdtemp())
    plugins_dir = tmpdir / "plugins"
    plugins_dir.mkdir()

    # Create a plugin file
    plugin_file = plugins_dir / "unlisted.py"
    plugin_file.write_text("def register_tools(reg): pass")

    reg = ToolRegistry()

    # Empty allowlist = skip everything
    with patch("nally.tools.registry.ALLOWED_PLUGINS", []):
        with patch("nally.tools.registry.PLUGINS_DIR", plugins_dir):
            reg.load_plugins()

    assert len(reg.tools) == 0

    shutil.rmtree(tmpdir)


def test_plugin_allowlist_loads_listed():
    """Plugin in allowlist is loaded."""
    tmpdir = Path(tempfile.mkdtemp())
    plugins_dir = tmpdir / "plugins"
    plugins_dir.mkdir()

    # Create a plugin file
    plugin_file = plugins_dir / "my_plugin.py"
    plugin_file.write_text(
        "from nally.tools.registry import Tool\n"
        "def register_tools(reg):\n"
        "    reg.register(Tool(name='plugin_tool', description='from plugin', permission='safe'))\n"
    )

    reg = ToolRegistry()

    with patch("nally.tools.registry.ALLOWED_PLUGINS", ["my_plugin.py"]):
        with patch("nally.tools.registry.PLUGINS_DIR", plugins_dir):
            reg.load_plugins()

    assert "plugin_tool" in reg.tools

    shutil.rmtree(tmpdir)


def test_plugin_allowlist_none_loads_all():
    """When ALLOWED_PLUGINS is None (not empty list), all plugins load."""
    tmpdir = Path(tempfile.mkdtemp())
    plugins_dir = tmpdir / "plugins"
    plugins_dir.mkdir()

    plugin_file = plugins_dir / "any_plugin.py"
    plugin_file.write_text(
        "from nally.tools.registry import Tool\n"
        "def register_tools(reg):\n"
        "    reg.register(Tool(name='any_tool', description='any', permission='safe'))\n"
    )

    reg = ToolRegistry()

    with patch("nally.tools.registry.ALLOWED_PLUGINS", None):
        with patch("nally.tools.registry.PLUGINS_DIR", plugins_dir):
            reg.load_plugins()

    assert "any_tool" in reg.tools

    shutil.rmtree(tmpdir)


def test_plugin_invalid_permission_blocks_registration():
    """Plugin tool with invalid permission fails at registration time."""
    tmpdir = Path(tempfile.mkdtemp())
    plugins_dir = tmpdir / "plugins"
    plugins_dir.mkdir()

    plugin_file = plugins_dir / "bad_plugin.py"
    plugin_file.write_text(
        "from nally.tools.registry import Tool\n"
        "def register_tools(reg):\n"
        "    reg.register(Tool(name='bad', description='bad perm', permission='INVALID'))\n"
    )

    reg = ToolRegistry()

    # Should not crash — the error is caught in load_plugins
    with patch("nally.tools.registry.ALLOWED_PLUGINS", ["bad_plugin.py"]):
        with patch("nally.tools.registry.PLUGINS_DIR", plugins_dir):
            reg.load_plugins()

    assert "bad" not in reg.tools

    shutil.rmtree(tmpdir)
