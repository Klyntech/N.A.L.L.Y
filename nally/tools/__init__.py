"""Nally Tools Package - Core tool registry"""
from .registry import registry, Tool

def load_all_tools():
    """Load all built-in tools"""
    from ..utils.logger import logger

    # --- System (5 tools) ---
    from .system import RunCommand, OpenApp, GetSystemInfo, SetVolume, GetVolume
    registry.register(RunCommand())
    registry.register(OpenApp())
    registry.register(GetSystemInfo())
    registry.register(SetVolume())
    registry.register(GetVolume())

    # --- Files (4 tools) ---
    from .files import ReadFile, WriteFile, ListFiles, CreateFolder
    registry.register(ReadFile())
    registry.register(WriteFile())
    registry.register(ListFiles())
    registry.register(CreateFolder())

    # --- Code Intelligence ---
    from .code import WriteCode, RunCode, RunPythonFile, RunTests
    registry.register(WriteCode())
    registry.register(RunCode())
    registry.register(RunPythonFile())
    registry.register(RunTests())

    # --- Memory (8 tools) ---
    from ..memory.store_v2 import memory_v2 as mem_store, memory_tools_v2 as mem_tools

    for tool_def in mem_tools.to_tool_list():
        func = tool_def["function"]

        class MemoryTool(Tool):
            def __init__(self, name, description, parameters, mem_store):
                super().__init__(name, description, parameters)
                self.mem_store = mem_store

            def execute(self, **kwargs):
                key = kwargs.get("key")
                value = kwargs.get("value")
                category = kwargs.get("category", "general")
                search = kwargs.get("search")
                topic = kwargs.get("topic")
                what_happened = kwargs.get("what_happened")
                outcome = kwargs.get("outcome", "")
                solution = kwargs.get("solution", "")
                tags = kwargs.get("tags", [])
                pattern = kwargs.get("pattern")
                min_confidence = kwargs.get("min_confidence", 0.5)

                if self.name == "remember":
                    return self.mem_store.remember(key, value, category)
                elif self.name == "recall":
                    result = self.mem_store.recall(key, category, search)
                    if result is None:
                        return "Nothing found in memory."
                    if isinstance(result, dict):
                        if not result:
                            return "Nothing found in memory."
                        lines = [f"{k}: {v}" for k, v in result.items()]
                        return "\n".join(lines)
                    return str(result)
                elif self.name == "forget":
                    return self.mem_store.forget(key)
                elif self.name == "remember_episode":
                    return self.mem_store.add_episode(topic, what_happened, outcome, solution, tags)
                elif self.name == "recall_episodes":
                    episodes = self.mem_store.search_episodes(topic, search)
                    if not episodes:
                        return "No episodes found."
                    lines = []
                    for ep in episodes[:5]:
                        date = ep["date"][:10] if ep["date"] else "?"
                        lines.append(f"[{date}] {ep['topic']}: {ep['what_happened'][:100]}")
                        if ep.get("solution"):
                            lines.append(f"  Solution: {ep['solution'][:100]}")
                    return "\n".join(lines)
                elif self.name == "memory_stats":
                    stats = self.mem_store.get_memory_stats()
                    return f"Total: {stats['total_memories']} memories | High confidence: {stats['high_confidence']} | Low confidence: {stats['low_confidence']} | Categories: {stats['by_category']}"
                elif self.name == "add_semantic_pattern":
                    return self.mem_store.add_semantic(pattern)
                elif self.name == "recall_semantic_patterns":
                    results = self.mem_store.recall_semantic(search, min_confidence)
                    if not results:
                        return "No semantic patterns found."
                    lines = []
                    for r in results[:10]:
                        lines.append(f"[{r['confidence']:.1f}] {r['pattern']} (seen {r['evidence_count']}x)")
                    return "\n".join(lines)
                return "Unknown memory operation"

        tool = MemoryTool(
            func["name"],
            func["description"],
            func["parameters"].get("properties", {}),
            mem_store,
        )
        registry.register(tool)

    # --- SubAgents (4 tools) ---
    from ..subagent.tools import register_tools as register_subagent_tools
    register_subagent_tools()

    # --- Load user plugins ---
    registry.load_plugins()

    logger.info(f"Nally loaded {len(registry.tools)} tools")

__all__ = ["registry", "Tool", "load_all_tools"]
