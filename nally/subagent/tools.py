"""SubAgent Tool - Delegate tasks to autonomous sub-agents"""
from ..tools.registry import Tool, registry
from .pool import pool


class Agent(Tool):
    """Manage sub-agents: delegate, spawn, collect, or check status."""

    def __init__(self):
        super().__init__(
            name="agent",
            description="Delegate tasks to sub-agents. Use delegate for single tasks, spawn for parallel work, collect to get results, status to check progress.",
            permission="safe",
            parameters={
                "action": {
                    "type": "string",
                    "enum": ["delegate", "spawn", "collect", "status"],
                    "description": "delegate = send one task and wait, spawn = launch parallel tasks, collect = get results, status = check progress",
                    "required": True,
                },
                "goal": {
                    "type": "string",
                    "description": "What the sub-agent should accomplish (for delegate/spawn)",
                },
                "context": {
                    "type": "string",
                    "description": "Background context the sub-agent needs (for delegate/spawn)",
                },
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string"},
                            "context": {"type": "string"},
                        },
                        "required": ["goal"],
                    },
                    "description": "List of tasks for spawn (each has goal + optional context)",
                },
                "task_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Task IDs to collect results or check status for",
                },
            },
        )

    def execute(self, action: str, goal: str = "", context: str = "", tasks=None, task_ids=None, **kwargs) -> str:
        try:
            if action == "delegate":
                if not goal:
                    return "Error: goal is required for delegate"
                agent_id = pool.spawn(goal, context)
                agent = pool._agents.get(agent_id)
                if not agent:
                    return "Error: failed to spawn sub-agent"
                result = agent.wait(timeout=300)
                if result:
                    return result
                if agent.error:
                    return f"Error: {agent.error}"
                return "Sub-agent did not return a result"

            elif action == "spawn":
                if not tasks:
                    return "Error: tasks list is required for spawn"
                ids = pool.spawn_many(tasks)
                return f"Spawned {len(ids)} sub-agents:\n" + "\n".join(
                    f"  {i+1}. {tid}" for i, tid in enumerate(ids)
                )

            elif action == "collect":
                if not task_ids:
                    return "Error: task_ids is required for collect"
                results = pool.get_results(task_ids)
                completed = [r for r in results if r.get("status") == "completed"]
                running = [r for r in results if r.get("status") in ("pending", "running")]
                lines = []
                if completed:
                    lines.append(f"Completed ({len(completed)}):")
                    for r in completed:
                        result_text = (r.get("result") or "")[:300]
                        lines.append(f"  [{r['id']}] {r['goal'][:80]}")
                        if result_text:
                            lines.append(f"    Result: {result_text}")
                if running:
                    lines.append(f"Still running ({len(running)}):")
                    for r in running:
                        lines.append(f"  [{r['id']}] {r['goal'][:80]}")
                if not results:
                    lines.append("No sub-agents found with those IDs.")
                return "\n".join(lines) if lines else "No results yet"

            elif action == "status":
                if task_ids:
                    agents = pool.get_results(task_ids)
                else:
                    agents = pool.get_all_status()
                if not agents:
                    return "No sub-agents found"
                lines = ["SubAgent Status:"]
                for a in agents:
                    icon = {"pending": "o", "running": "*", "completed": "v", "failed": "x", "cancelled": "-"}.get(
                        a.get("status", ""), "?"
                    )
                    lines.append(f"  {icon} [{a['id']}] {a['goal'][:80]}")
                    if a.get("error"):
                        lines.append(f"    Error: {a['error']}")
                return "\n".join(lines)

            else:
                return f"Unknown action: {action}. Use delegate, spawn, collect, or status."
        except Exception as e:
            return f"Error: {str(e)}"


def register_tools():
    """Register subagent tools"""
    registry.register(Agent())
