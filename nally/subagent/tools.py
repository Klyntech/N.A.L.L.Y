"""SubAgent Tools - Delegate tasks to autonomous sub-agents"""
from ..tools.registry import Tool, registry
from .pool import pool
from .decomposer import decomposer


class Delegate(Tool):
    """Send a task to a sub-agent. Blocks until result is ready."""

    def __init__(self):
        super().__init__(
            name="delegate",
            description="Send a subtask to an autonomous sub-agent. Returns the complete result. Use for complex operations that need their own AI reasoning session.",
            permission="destructive",
            parameters={
                "goal": {
                    "type": "string",
                    "description": "What the sub-agent should accomplish. Be specific and clear.",
                },
                "context": {
                    "type": "string",
                    "description": "Background context or files the sub-agent needs to know",
                },
            },
        )

    def execute(self, goal: str = "", context: str = "", **kwargs) -> str:
        if not goal:
            return "Error: goal is required."

        agent_id = pool.spawn(goal, context)
        agent = pool._agents.get(agent_id)
        if not agent:
            return "Error: failed to spawn sub-agent."

        result = agent.wait(timeout=300)
        if result:
            return result
        if agent.error:
            return f"Error: {agent.error}"
        return "Sub-agent did not return a result."


class SpawnAgents(Tool):
    """Spawn multiple sub-agents in parallel. Returns task IDs for status checking."""

    def __init__(self):
        super().__init__(
            name="spawn_agents",
            description="Spawn multiple sub-agents in parallel. Each gets its own goal. Returns task IDs you can check with agent_status or collect_results.",
            permission="destructive",
            parameters={
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "goal": {
                                "type": "string",
                                "description": "What this sub-agent should do",
                            },
                            "context": {
                                "type": "string",
                                "description": "Context for this sub-agent",
                            },
                        },
                        "required": ["goal"],
                    },
                    "description": "List of tasks. Each task has a goal and optional context.",
                },
            },
        )

    def execute(self, tasks=None, **kwargs) -> str:
        if not tasks:
            return "Error: tasks list is required."

        ids = pool.spawn_many(tasks)
        return f"Spawned {len(ids)} sub-agents:\n" + "\n".join(f"  {i+1}. {tid}" for i, tid in enumerate(ids))


class CollectResults(Tool):
    """Get results from spawned sub-agents. Returns completed results and still-running agents."""

    def __init__(self):
        super().__init__(
            name="collect_results",
            description="Get results from spawned sub-agents. Returns completed results and lists any still-running agents.",
            parameters={
                "task_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of task IDs to collect results for",
                },
            },
        )

    def execute(self, task_ids=None, **kwargs) -> str:
        if not task_ids:
            return "Error: task_ids is required."

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
                lines.append("")

        if running:
            lines.append(f"Still running ({len(running)}):")
            for r in running:
                lines.append(f"  [{r['id']}] {r['goal'][:80]}")

        if not results:
            lines.append("No sub-agents found with those IDs.")

        return "\n".join(lines) if lines else "No results yet."


class AgentStatus(Tool):
    """Check the status of spawned sub-agents."""

    def __init__(self):
        super().__init__(
            name="agent_status",
            description="Check the current status of one or more spawned sub-agents.",
            parameters={
                "task_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of task IDs to check",
                },
            },
        )

    def execute(self, task_ids=None, **kwargs) -> str:
        if not task_ids:
            # Return status of all agents
            agents = pool.get_all_status()
        else:
            agents = pool.get_results(task_ids)

        if not agents:
            return "No sub-agents found."

        lines = ["SubAgent Status:"]
        for a in agents:
            status_icon = {
                "pending": "○",
                "running": "●",
                "completed": "✓",
                "failed": "✗",
                "cancelled": "—",
            }.get(a.get("status", ""), "?")

            lines.append(f"  {status_icon} [{a['id']}] {a['goal'][:80]}")
            if a.get("error"):
                lines.append(f"    Error: {a['error']}")

        return "\n".join(lines)


def register_tools():
    """Register subagent tools"""
    tools = [
        Delegate(),
        SpawnAgents(),
        CollectResults(),
        AgentStatus(),
    ]
    for tool in tools:
        registry.register(tool)
