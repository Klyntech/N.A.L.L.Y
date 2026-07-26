"""Tool Registry and Plugin System"""
import importlib
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from ..config import PLUGINS_DIR, ALLOWED_PLUGINS

MAX_TOOL_OUTPUT = 4000  # Max chars before truncation (~1000 tokens)

VALID_PERMISSIONS = {"safe", "destructive", "write", "read_only"}

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
        clean_props = {}
        for k, v in self.parameters.items():
            clean_props[k] = {pk: pv for pk, pv in v.items() if pk != "required"}
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": clean_props,
                    "required": [k for k, v in self.parameters.items() if v.get("required", False)]
                }
            }
        }

class ToolRegistry:
    """Registry for all available tools"""
    
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
    
    def register(self, tool: Tool):
        """Register a tool (warn if overwriting, validate permission)"""
        if tool.permission not in VALID_PERMISSIONS:
            raise ValueError(
                f"Tool '{tool.name}' has invalid permission '{tool.permission}'. "
                f"Must be one of: {', '.join(sorted(VALID_PERMISSIONS))}"
            )
        if tool.name in self.tools:
            logger.warning(f"Tool '{tool.name}' already registered — overwriting")
        self.tools[tool.name] = tool
    
    def unregister(self, name: str):
        """Unregister a tool"""
        if name in self.tools:
            del self.tools[name]
    
    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name"""
        return self.tools.get(name)
    
    def get_all_tools(self) -> List[dict]:
        """Get all tools as OpenAI schemas"""
        return [tool.to_openai_schema() for tool in self.tools.values()]
    
    def execute(self, name: str, arguments: dict) -> str:
        """Execute a tool by name with output truncation"""
        tool = self.tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found"
        
        try:
            result = tool.execute(**arguments)
            if isinstance(result, str) and len(result) > MAX_TOOL_OUTPUT:
                result = result[:MAX_TOOL_OUTPUT] + f"\n... [truncated, {len(result)} chars total]"
            return result
        except Exception as e:
            return f"Error executing {name}: {type(e).__name__}: {e}"
    
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
                spec = importlib.util.spec_from_file_location(
                    f"nally_plugin_{plugin_file.stem}", plugin_file
                )
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

registry = ToolRegistry()
