"""Registry for the fixed set of tools exposed to Nally."""

import logging
import re
import threading
from typing import Dict, List, Optional

from ..config import MAX_TOOL_OUTPUT
from ..core.errors import ToolError

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
        """Get a tool by name."""
        with self._lock:
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
        with self._lock:
            tool = self.tools.get(name)
        if not tool:
            # Lazy-load: if tools haven't been loaded yet (e.g., early agent call
            # before web lifespan), try to load now. This prevents the
            # "Tool not found" race seen in receipts during early initialization.
            try:
                from . import _loaded, load_all_tools

                if not _loaded:
                    load_all_tools()
                    with self._lock:
                        tool = self.tools.get(name)
            except Exception:
                pass
        if not tool:
            # Still not found — give a helpful hint for the two core tools
            if name in ("run_command", "read_file", "file_ops"):
                return (
                    f"Error: Tool '{name}' not found (registry not yet initialized — try again, or check load_all_tools() was called)",
                    False,
                )
            return f"Error: Tool '{name}' not found", False

        try:
            result = tool.execute(**arguments)
            result = str(result)
            if len(result) > MAX_TOOL_OUTPUT:
                result = result[:MAX_TOOL_OUTPUT] + f"\n... [truncated, {len(result)} chars total]"
            success = _result_is_success(name, result)
            return result, success
        except ToolError as e:
            logger.warning(f"Tool '{name}' raised ToolError: {e.code}: {e.message}")
            result = e.to_llm_format()
            if len(result) > MAX_TOOL_OUTPUT:
                result = result[:MAX_TOOL_OUTPUT] + f"\n... [truncated, {len(result)} chars total]"
            return result, False
        except Exception as e:
            logger.error(f"Tool '{name}' execution failed: {type(e).__name__}: {e}")
            return f"Error executing {name}: {type(e).__name__}: {e}", False


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
    # ToolError.to_llm_format() starts with "Error: <message>"
    if r.startswith("Error:"):
        return False
    if tool_name == "run_command":
        m = re.search(r"Exit code:\s*(\d+)\s*$", r)
        if m and int(m.group(1)) != 0:
            return False
    return True


registry = ToolRegistry()
