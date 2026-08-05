"""SubAgent - An autonomous sub-agent with its own LLM session, tools, and message history"""

import threading
import uuid
from datetime import datetime
from typing import Callable, Dict, List, Optional

from ..tools.registry import registry
from ..utils.logger import logger


def _get_filtered_tools(query: str) -> List[Dict]:
    """Get tool schemas filtered for the given query."""
    try:
        from ..tools.filter import tool_filter

        if not tool_filter._ready:
            tool_filter.build_index(registry.tools)
        return tool_filter.select(query)
    except ImportError:
        return [t.to_openai_schema() for t in registry.tools.values()]


class SubAgent:
    """An autonomous sub-agent that can think, use tools, and return results"""

    def __init__(self, goal: str, context: str = "", agent_id: str = None, model: str = None):
        self.id = agent_id or f"sub_{uuid.uuid4().hex[:8]}"
        self.goal = goal
        self.context = context
        self.model = model
        self.status = "pending"
        self.result: Optional[str] = None
        self.error: Optional[str] = None
        self.messages: List[Dict] = []
        self.created_at = datetime.now().isoformat()
        self.completed_at: Optional[str] = None
        self.steps_taken: List[str] = []
        self._lock = threading.Lock()
        self._emit: Optional[Callable] = None
        self._thread: Optional[threading.Thread] = None

    def set_callback(self, callback: Optional[Callable]):
        """Set progress reporting callback."""
        self._emit = callback

    def _emit_event(self, event: str, data: dict):
        """Emit event if callback is set."""
        if self._emit:
            try:
                self._emit(event, data)
            except Exception:
                pass

    def start(self, emit: Optional[Callable] = None):
        """Start the sub-agent in its own thread."""
        if emit:
            self._emit = emit
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"SubAgent-{self.id}")
        self._thread.start()

    def _run(self):
        """Run the sub-agent autonomously."""
        with self._lock:
            self.status = "running"

        self._emit_event(
            "subagent_status",
            {
                "id": self.id,
                "goal": self.goal,
                "status": "running",
            },
        )

        self.messages = [
            {
                "role": "system",
                "content": (
                    f"You are a focused sub-agent. Your sole goal is:\n{self.goal}\n\n"
                    f"Context:\n{self.context}\n\n"
                    "OUTPUT FORMAT: End your response with a structured summary in this exact format:\n"
                    "---RESULT---\n"
                    "STATUS: success|failure|partial\n"
                    "SUMMARY: [one-line summary]\n"
                    'FILES_CHANGED: [comma-separated list or "none"]\n'
                    'KEY_FINDINGS: [bullet points or "none"]\n'
                    "---END---\n\n"
                    "Complete your goal using the available tools. Be concise. NO EMOJIS."
                ),
            },
            {"role": "user", "content": self.goal},
        ]

        try:
            result = self._agent_loop()
            with self._lock:
                self.result = result
                self.status = "completed"
                self.completed_at = datetime.now().isoformat()

            self._emit_event(
                "subagent_result",
                {
                    "id": self.id,
                    "goal": self.goal,
                    "result": result[:500],
                    "steps": self.steps_taken,
                },
            )
            logger.debug(f"SubAgent {self.id} completed: {result[:100]}")

        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.status = "failed"
                self.completed_at = datetime.now().isoformat()

            self._emit_event(
                "subagent_error",
                {
                    "id": self.id,
                    "goal": self.goal,
                    "error": str(e),
                },
            )
            logger.error(f"SubAgent {self.id} failed: {e}")

    def _agent_loop(self) -> str:
        """Run the agent loop using LangGraph."""
        from ..agent.graph import run_agent

        tools = _get_filtered_tools(self.goal)
        selected_names = [t["function"]["name"] for t in tools]
        logger.debug(f"SubAgent {self.id}: selected {len(tools)} tools: {selected_names}")

        self._emit_event(
            "subagent_status",
            {
                "id": self.id,
                "status": "thinking",
                "tools": selected_names,
            },
        )

        return run_agent(
            messages=self.messages,
            tools=tools,
            emit=self._emit,
            max_iterations=15,
            thread_id=self.id,
            model=self.model,
        )

    def get_status(self) -> dict:
        """Get current status."""
        with self._lock:
            return {
                "id": self.id,
                "goal": self.goal,
                "status": self.status,
                "result": self.result[:500] if self.result else None,
                "error": self.error,
                "steps": len(self.steps_taken),
                "created_at": self.created_at,
                "completed_at": self.completed_at,
            }

    def wait(self, timeout: float = 300.0) -> Optional[str]:
        """Wait for sub-agent to complete."""
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        return self.result

    def to_dict(self) -> dict:
        return self.get_status()
