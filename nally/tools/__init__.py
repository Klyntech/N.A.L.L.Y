"""Nally Tools Package - Core tool registry"""
import json
from .registry import registry, Tool


def load_all_tools():
    """Load all built-in tools"""
    from ..utils.logger import logger

    # --- System (2 tools) ---
    from .system import RunCommand, SystemHealth
    registry.register(RunCommand())
    registry.register(SystemHealth())

    # --- Files (2 tools) ---
    from .files import ReadFile, FileOps
    registry.register(ReadFile())
    registry.register(FileOps())

    # --- Code (2 tools) ---
    from .code import RunCode, CodeAnalysis
    registry.register(RunCode())
    registry.register(CodeAnalysis())

    # --- Memory (3 tools) ---
    from ..memory.store_v2 import memory_v2 as mem_store, memory_tools_v2 as mem_tools

    for tool_def in mem_tools.to_tool_list():
        func = tool_def["function"]

        class MemoryTool(Tool):
            def __init__(self, name, description, parameters, mem_store):
                super().__init__(name, description, parameters)
                self.mem_store = mem_store

            def execute(self, **kwargs):
                memory_type = kwargs.get("type", "fact")

                if self.name == "remember":
                    if memory_type == "episode":
                        topic = kwargs.get("topic", "")
                        what_happened = kwargs.get("what_happened", "")
                        outcome = kwargs.get("outcome", "")
                        solution = kwargs.get("solution", "")
                        tags = kwargs.get("tags", [])
                        return self.mem_store.add_episode(topic, what_happened, outcome, solution, tags)
                    else:
                        key = kwargs.get("key", "")
                        value = kwargs.get("value", "")
                        category = kwargs.get("category", "general")
                        return self.mem_store.remember(key, value, category)

                elif self.name == "recall":
                    if memory_type == "episode":
                        topic = kwargs.get("topic", "")
                        search = kwargs.get("search", "")
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
                    else:
                        key = kwargs.get("key", "")
                        category = kwargs.get("category", "")
                        search = kwargs.get("search", "")

                        # Profile summary: return formatted profile view
                        if category == "profile" and not key:
                            result = self.mem_store.recall(category="profile")
                            if not result or not isinstance(result, dict):
                                return "No profile data found."
                            lines = []
                            if result.get("name"):
                                lines.append(f"Name: {result['name']}")
                            if result.get("preferred_name") and result["preferred_name"] != result.get("name"):
                                lines.append(f"Preferred name: {result['preferred_name']}")
                            if result.get("aliases"):
                                try:
                                    aliases = json.loads(result["aliases"]) if isinstance(result["aliases"], str) else result["aliases"]
                                    lines.append(f"Also known as: {', '.join(aliases)}")
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            if result.get("age"):
                                lines.append(f"Age: {result['age']}")
                            if result.get("location"):
                                lines.append(f"Location: {result['location']}")
                            if result.get("occupation"):
                                lines.append(f"Occupation: {result['occupation']}")
                            if result.get("education"):
                                lines.append(f"Education: {result['education']}")
                            if result.get("timezone"):
                                lines.append(f"Timezone: {result['timezone']}")
                            if result.get("languages_spoken"):
                                try:
                                    langs = json.loads(result["languages_spoken"]) if isinstance(result["languages_spoken"], str) else result["languages_spoken"]
                                    lines.append(f"Languages: {', '.join(langs)}")
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            if result.get("coding_level"):
                                lines.append(f"Coding level: {result['coding_level']}")
                            if result.get("coding_languages"):
                                try:
                                    langs = json.loads(result["coding_languages"]) if isinstance(result["coding_languages"], str) else result["coding_languages"]
                                    lines.append(f"Coding languages: {', '.join(langs)}")
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            if result.get("projects"):
                                try:
                                    proj = json.loads(result["projects"]) if isinstance(result["projects"], str) else result["projects"]
                                    lines.append(f"Projects: {', '.join(proj)}")
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            if result.get("goals"):
                                try:
                                    goals = json.loads(result["goals"]) if isinstance(result["goals"], str) else result["goals"]
                                    lines.append(f"Goals: {', '.join(goals)}")
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            if result.get("interests"):
                                try:
                                    interests = json.loads(result["interests"]) if isinstance(result["interests"], str) else result["interests"]
                                    lines.append(f"Interests: {', '.join(interests)}")
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            if result.get("notes"):
                                lines.append(f"Notes: {result['notes']}")
                            return "\n".join(lines) if lines else "No profile data found."

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
                    key = kwargs.get("key", "")
                    return self.mem_store.forget(key)

                return "Unknown memory operation"

        tool = MemoryTool(
            func["name"],
            func["description"],
            func["parameters"].get("properties", {}),
            mem_store,
        )
        registry.register(tool)

    # --- Memory Stats (1 tool) ---
    class MemoryStats(Tool):
        def __init__(self, mem_store):
            super().__init__(
                name="memory_stats",
                description="Get statistics about stored memories: total count, category breakdown, confidence distribution.",
            )
            self.mem_store = mem_store

        def execute(self, **kwargs) -> str:
            stats = self.mem_store.get_memory_stats()
            lines = [f"Total memories: {stats['total_memories']}"]
            if stats.get("by_category"):
                cats = ", ".join(f"{k}: {v}" for k, v in stats["by_category"].items())
                lines.append(f"By category: {cats}")
            lines.append(f"High confidence (>=0.8): {stats.get('high_confidence', 0)}")
            lines.append(f"Low confidence (<0.5): {stats.get('low_confidence', 0)}")
            return "\n".join(lines)

    registry.register(MemoryStats(mem_store))

    # --- One-time profile migration ---
    from ..memory.store import migrate_profile
    migrate_profile(mem_store)

    # --- SubAgents (1 tool) ---
    from ..subagent.tools import register_tools as register_subagent_tools
    register_subagent_tools()

    # --- Load user plugins ---
    registry.load_plugins()

    logger.info(f"Nally loaded {len(registry.tools)} tools")


__all__ = ["registry", "Tool", "load_all_tools"]
