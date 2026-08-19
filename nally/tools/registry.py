"""Tool Registry and Plugin System"""

import importlib
import logging
import re
import threading
from typing import Dict, List, Optional

from ..config import ALLOWED_PLUGINS, MAX_TOOL_OUTPUT, PLUGINS_DIR

VALID_PERMISSIONS = {"safe", "destructive", "read_only", "write"}

logger = logging.getLogger("nally.registry")


class Tool:
    """Base class for all Nally tools"""

    def __init__(self, name: str, description: str, parameters: dict = None, permission: str = "safe"):
        self.name = name
        self.description = description
        self.parameters = parameters or {}
        self.permission = permission  # "safe", "destructive", "read_only"

    def execute(self, **kwargs) -> str:
        """Override this method in subclasses"""
        raise NotImplementedError

    def to_openai_schema(self) -> dict:
        """Convert tool to OpenAI function calling schema"""
        # Truncate MCP tool descriptions to save tokens (200+ tools = massive context)
        desc = self.description
        if self.name.startswith("mcp_") and len(desc) > 150:
            desc = desc[:150].rsplit(" ", 1)[0] + "..."

        clean_props = {}
        for k, v in self.parameters.items():
            clean_props[k] = {pk: pv for pk, pv in v.items() if pk != "required"}

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": clean_props,
                    "required": [k for k, v in self.parameters.items() if v.get("required", False)],
                },
            },
        }


class ToolRegistry:
    """Registry for all available tools"""

    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        # Guards the tools dict: mutated at startup (register/unregister,
        # plugin load) and iterated at runtime (get_all_tools, filter, mcp).
        self._lock = threading.Lock()

    def register(self, tool: Tool):
        """Register a tool (warn if overwriting, validate permission)"""
        if tool.permission not in VALID_PERMISSIONS:
            raise ValueError(
                f"Tool '{tool.name}' has invalid permission '{tool.permission}'. "
                f"Must be one of: {', '.join(sorted(VALID_PERMISSIONS))}"
            )
        with self._lock:
            if tool.name in self.tools:
                logger.warning(f"Tool '{tool.name}' already registered — overwriting")
            self.tools[tool.name] = tool

    def unregister(self, name: str):
        """Unregister a tool"""
        with self._lock:
            if name in self.tools:
                del self.tools[name]

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name"""
        return self.tools.get(name)

    def get_all_tools(self) -> List[dict]:
        """Get all tools as OpenAI schemas"""
        with self._lock:
            tools = list(self.tools.values())
        return [tool.to_openai_schema() for tool in tools]

    def execute(self, name: str, arguments: dict) -> tuple[str, bool]:
        """Execute a tool by name with output truncation.

        Returns:
            (result, success) — result string and whether the tool succeeded.
            success is determined by the tool itself returning normally (no exception)
            OR by checking if the result starts with "Error" as a fallback.
        """
        tool = self.tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found", False

        try:
            result = tool.execute(**arguments)
            result = str(result)
            if len(result) > MAX_TOOL_OUTPUT:
                result = result[:MAX_TOOL_OUTPUT] + f"\n... [truncated, {len(result)} chars total]"
            success = _result_is_success(name, result)
            return result, success
        except Exception as e:
            logger.error(f"Tool '{name}' execution failed: {type(e).__name__}: {e}")
            return f"Error executing {name}: {type(e).__name__}: {e}", False

    def load_plugins(self):
        """Load plugins from the plugins directory (allowlist-gated, safe import)"""
        if not PLUGINS_DIR.exists():
            PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
            return

        for plugin_file in PLUGINS_DIR.glob("*.py"):
            if plugin_file.name.startswith("_"):
                continue
            if ALLOWED_PLUGINS and plugin_file.name not in ALLOWED_PLUGINS:
                logger.debug(f"Skipping plugin '{plugin_file.name}' — not in allowlist")
                continue

            try:
                spec = importlib.util.spec_from_file_location(f"nally_plugin_{plugin_file.stem}", plugin_file)
                if not spec or not spec.loader:
                    logger.warning(f"Cannot load plugin: {plugin_file.name}")
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                if hasattr(module, "register_tools"):
                    module.register_tools(self)
                    logger.info(f"Loaded plugin: {plugin_file.name}")
                else:
                    logger.debug(f"Plugin {plugin_file.name} has no register_tools()")
            except Exception as e:
                logger.error(f"Error loading plugin {plugin_file.name}: {type(e).__name__}: {e}")


def _result_is_success(tool_name: str, result: str) -> bool:
    """Decide success from the tool result string.

    Contract: a result that begins with "Error" (case-insensitive) is a
    failure. For run_command we additionally trust the process exit code
    encoded as a trailing "Exit code: N" line, since commands can emit
    error-like text on stdout while still succeeding (and vice versa).

    This is the authoritative success signal consumed by the agent graph;
    the post-execution validation in graph.py only acts as a defense-in-depth
    net for unmistakable crash signals.
    """
    r = (result or "").strip()
    if not r:
        return True
    if r[:5].lower() == "error":
        return False
    if tool_name == "run_command":
        m = re.search(r"Exit code:\s*(\d+)\s*$", r)
        if m and int(m.group(1)) != 0:
            return False
    return True


registry = ToolRegistry()
