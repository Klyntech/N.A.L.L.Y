"""Register Nally's small default core toolset.

The core tools are registered here. Explicit MCP service connections may register
additional tools at runtime; the model receives the current registry schemas.
User plugins are not loaded.
"""

import threading

from .registry import Tool, registry

_loaded = False
_loaded_lock = threading.Lock()


def _load_all_registered():
    """Register only Nally's approved core tools."""
    global _loaded

    # Local command execution: run_command only (no system_health).
    from .system import RunCommand

    registry.register(RunCommand())

    # Persistent managed shell sessions (list, output polling, stdin).
    from .managed import ShellOutput, ShellSessions, ShellStdin

    registry.register(ShellSessions())
    registry.register(ShellOutput())
    registry.register(ShellStdin())

    # File I/O: read and manage files.
    from .files import FileOps, ReadFile

    registry.register(ReadFile())
    registry.register(FileOps())

    # Web research: search results plus full-page fetching.
    from .fetch import FetchTool
    from .websearch import WebSearch

    registry.register(WebSearch())
    registry.register(FetchTool())

    # Durable memory: remember, recall, forget. No memory_stats tool.
    from ..memory import memory_store as mem_store
    from ..memory import memory_tools_v2 as mem_tools

    class MemoryTool(Tool):
        def __init__(self, name, description, parameters):
            super().__init__(name, description, parameters)
            self.mem_store = mem_store

        def execute(self, **kwargs):
            memory_type = kwargs.get("type", "fact")

            if self.name == "remember":
                if memory_type == "episode":
                    return self.mem_store.add_episode(
                        kwargs.get("topic", ""),
                        kwargs.get("what_happened", ""),
                        kwargs.get("outcome", ""),
                        kwargs.get("solution", ""),
                        kwargs.get("tags", []),
                    )
                key, value = kwargs.get("key", ""), kwargs.get("value", "")
                if not str(key).strip() or not str(value).strip():
                    return "Error: key and value are required and must be non-empty."
                return self.mem_store.remember(key, value, kwargs.get("category", "general"))

            if self.name == "recall":
                if memory_type == "episode":
                    episodes = self.mem_store.search_episodes(kwargs.get("topic", ""), kwargs.get("search", ""))
                    if not episodes:
                        return "No episodes found."
                    lines = []
                    for ep in episodes[:5]:
                        date = ep["date"][:10] if ep.get("date") else "?"
                        lines.append(f"[{date}] {ep['topic']}: {ep['what_happened'][:200]}")
                        if ep.get("solution"):
                            lines.append(f"  Solution: {ep['solution'][:200]}")
                    return "\n".join(lines)

                result = self.mem_store.recall(
                    kwargs.get("key", ""),
                    kwargs.get("category", ""),
                    kwargs.get("search", ""),
                )
                if result is None or result == {}:
                    return "Nothing found in memory."
                if isinstance(result, dict):
                    return "\n".join(f"{key}: {value}" for key, value in result.items())
                return str(result)

            if self.name == "forget":
                key = kwargs.get("key", "")
                if not key.strip():
                    return "Error: key is required."
                return self.mem_store.forget(key)

            return "Error: unknown memory operation."

    for tool_def in mem_tools.to_tool_list():
        func = tool_def["function"]
        if func["name"] not in {"remember", "recall", "forget"}:
            continue
        properties = func["parameters"].get("properties", {})
        registry.register(MemoryTool(func["name"], func["description"], properties))

    # Preserve the one-time profile migration used by durable memory.
    from ..memory.store import migrate_profile

    migrate_profile(mem_store)

    # Task delegation.
    from ..subagent.tools import register_tools as register_subagent_tools

    register_subagent_tools()

    # Remote execution through connected NallyBridge devices.
    from . import bridge

    bridge.register(registry)

    _loaded = True
    return []


def load_all_tools():
    """Load default core tools. Returns (current tool count, startup MCP status)."""
    global _loaded
    with _loaded_lock:
        if not _loaded:
            mcp_status = _load_all_registered()
        else:
            mcp_status = []
    return len(registry.tools), mcp_status


__all__ = ["Tool", "load_all_tools", "registry"]
