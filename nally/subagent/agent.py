"""SubAgent - An autonomous sub-agent with its own LLM session, tools, and message history"""

import threading
import uuid
from datetime import datetime
from typing import Callable, Dict, List, Optional

from ..tools.registry import registry
from ..utils.logger import logger
from ..core.tracing import tracer


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

    def __init__(self, goal: str, context: str = "", agent_id: str = None, model: str = None, depth: int = 0):
        self.id = agent_id or f"sub_{uuid.uuid4().hex[:8]}"
        self.goal = goal
        self.context = context
        self.model = model
        self.depth = depth
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
        # Tracing context captured at spawn time (thread-local span stack does
        # not propagate into this sub-agent's own thread).
        self._trace_parent_span_id: Optional[str] = None
        self._trace_run_id: Optional[str] = None

    def set_callback(self, callback: Optional[Callable]):
        """Set progress reporting callback."""
        self._emit = callback

    def set_trace_context(self, parent_span_id: Optional[str], run_id: Optional[str]):
        """Set the tracing parent context captured at spawn time."""
        self._trace_parent_span_id = parent_span_id
        self._trace_run_id = run_id

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
        # Publish our nesting depth on the contextvar so that any sub-agent we
        # spawn (via the agent tool, executed in a pooled worker thread) is
        # correctly bounded by MAX_SUBAGENT_DEPTH in the pool.
        _depth_token = None
        try:
            from .pool import SUBAGENT_DEPTH

            _depth_token = SUBAGENT_DEPTH.set(self.depth)
        except Exception:
            pass

        with self._lock:
            self.status = "running"

        sub_span = None
        try:
            sub_span = tracer.start_span(
                f"subagent:{self.id}",
                {"goal": self.goal, "context": self.context, "model": self.model},
                parent_span_id=self._trace_parent_span_id,
                run_id=self._trace_run_id,
            )
        except Exception:
            sub_span = None

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
                    f"You are a focused sub-agent operating under Nally. Your sole goal is:\n{self.goal}\n\n"
                    f"Context:\n{self.context}\n\n"
                    "HOW YOU WORK (inherited, non-negotiable):\n"
                    "- Read before you write. Understand what's already there before changing it.\n"
                    "- Identify root cause before proposing a fix. Don't guess.\n"
                    "- Verify your work before claiming it's done. If you can't verify it, say so.\n"
                    "- Never hardcode or echo a credential, even one you find while working.\n"
                    "- Before a destructive or hard-to-reverse action, name the risk in your own reasoning — "
                    "the permission gate will still pause for approval on risky calls, but state it anyway.\n"
                    "- If a tool call fails, say it failed. Never claim success without a tool result proving it.\n"
                    "- Stay inside your goal. Don't expand scope into the parent task's other subtasks.\n\n"
                    "OUTPUT FORMAT: End your response with a structured summary in this exact format:\n"
                    "---RESULT---\n"
                    "STATUS: success|failure|partial\n"
                    "SUMMARY: [one-line summary]\n"
                    'FILES_CHANGED: [comma-separated list or "none"]\n'
                    'KEY_FINDINGS: [bullet points or "none"]\n'
                    'ROOT_CAUSE: [if STATUS is failure or partial, one sentence why; otherwise "n/a"]\n'
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

            if sub_span is not None:
                try:
                    tracer.end_span(sub_span.span_id, output={"result": result, "status": "completed"})
                except Exception:
                    pass

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

            if sub_span is not None:
                try:
                    tracer.end_span_exc(sub_span.span_id, e)
                except Exception:
                    pass

            self._emit_event(
                "subagent_error",
                {
                    "id": self.id,
                    "goal": self.goal,
                    "error": str(e),
                },
            )
            logger.error(f"SubAgent {self.id} failed: {e}")

        finally:
            # Restore the nesting depth contextvar set at the top of _run.
            if _depth_token is not None:
                try:
                    from .pool import SUBAGENT_DEPTH

                    SUBAGENT_DEPTH.reset(_depth_token)
                except Exception:
                    pass

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

        cur = tracer.get_current_span()
        child_parent = cur.span_id if cur else self._trace_parent_span_id
        child_run = cur.run_id if cur else self._trace_run_id

        return run_agent(
            messages=self.messages,
            tools=tools,
            emit=self._emit,
            max_iterations=15,
            thread_id=self.id,
            _parent_span_id=child_parent,
            _run_id=child_run,
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
