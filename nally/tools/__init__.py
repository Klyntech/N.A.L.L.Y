"""Nally Tools package — thin exports only.

Application startup must call ``load_all_tools()`` explicitly (see
``registry_builder``). Importing this package does not register tools or
connect MCP servers.
"""

from .registry import Tool, registry
from .registry_builder import ToolRegistryBuilder, is_tools_loaded, load_all_tools

__all__ = [
    "Tool",
    "ToolRegistryBuilder",
    "is_tools_loaded",
    "load_all_tools",
    "registry",
]
