"""Tool Registry and Plugin System"""

import importlib
import logging
import re
import threading
from typing import Dict, List, Optional

from ..config import ALLOWED_PLUGINS, MAX_TOOL_OUTPUT, PLUGINS_DIR
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

    def execute(self, **kwargs):
        """Override in subclasses. Return ``str`` (legacy) or ``ToolResult``."""
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

    def execute_result(self, name: str, arguments: dict):
        """Execute a tool by name and return a structured ``ToolResult``.

        This is the canonical execution boundary. Legacy ``execute()`` remains
        as a thin ``(text, success)`` adapter for existing callers.
        """
        from .result import ToolResult, _safe_metadata

        tool = self.tools.get(name)
        if not tool:
            try:
                from .registry_builder import is_tools_loaded, load_all_tools

                if not is_tools_loaded():
                    load_all_tools()
                    tool = self.tools.get(name)
            except Exception:
                pass
        if not tool:
            if name in ("run_code", "run_command", "read_file", "file_ops"):
                msg = (
                    f"Error: Tool '{name}' not found (registry not yet initialized — "
                    "try again, or check load_all_tools() was called)"
                )
            else:
                msg = f"Error: Tool '{name}' not found"
            return ToolResult.failure(error=msg, tool=name)

        try:
            raw = tool.execute(**(arguments or {}))
            # Structured tools may return ToolResult directly
            from .result import ToolResult as _TR

            if isinstance(raw, _TR):
                tr = raw
            else:
                tr = _TR.from_legacy(name, raw)

            # Truncate LLM-facing text if needed
            text = tr.to_llm_text()
            if len(text) > MAX_TOOL_OUTPUT:
                text = text[:MAX_TOOL_OUTPUT] + f"\n... [truncated, {len(text)} chars total]"
                if tr.ok:
                    tr = _TR.success(value=text, **_safe_metadata(tr.metadata))
                else:
                    tr = _TR.failure(error=text, value=text, **_safe_metadata(tr.metadata))
            # Ensure tool name is present for observability (non-secret)
            if "tool" not in tr.metadata:
                tr.metadata = {**tr.metadata, "tool": name}
            tr.metadata = _safe_metadata(tr.metadata)
            return tr
        except ToolError as e:
            logger.warning("Tool '%s' raised ToolError: %s: %s", name, e.code, e.message)
            result = e.to_llm_format()
            if len(result) > MAX_TOOL_OUTPUT:
                result = result[:MAX_TOOL_OUTPUT] + f"\n... [truncated, {len(result)} chars total]"
            return ToolResult.failure(error=result, value=result, tool=name, code=getattr(e, "code", None))
        except Exception as e:
            logger.error("Tool '%s' execution failed: %s: %s", name, type(e).__name__, e)
            msg = f"Error executing {name}: {type(e).__name__}: {e}"
            return ToolResult.failure(error=msg, value=msg, tool=name, exception_type=type(e).__name__)

    def execute(self, name: str, arguments: dict) -> tuple[str, bool]:
        """Execute a tool by name with output truncation.

        Returns:
            (result, success) — compatibility adapter over ``execute_result``.
            Prefer ``execute_result`` for new callers.
        """
        return self.execute_result(name, arguments).as_tuple()

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
    # ToolError.to_llm_format() starts with "Error: <message>"
    if r.startswith("Error:"):
        return False
    if tool_name == "run_command":
        m = re.search(r"Exit code:\s*(\d+)\s*$", r)
        if m and int(m.group(1)) != 0:
            return False
    return True


registry = ToolRegistry()
