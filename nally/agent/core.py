"""Nally Core Agent - The Brain"""

import threading
import time
from datetime import UTC, datetime
from typing import Callable, List, Optional

from ..config import CONTEXT_MAX_TOKENS as MAX_CONTEXT_TOKENS
from ..config import MAX_ITERATIONS_PER_TURN, SESSION_ID, get_system_prompt
from ..core.errors import LLMError, NallyError
from ..memory import memory_store
from ..utils.logger import logger


def _get_tool_schemas() -> list[dict]:
    """Initialize core tools before exposing schemas to the model."""
    from ..tools import load_all_tools
    from ..tools.registry import registry

    load_all_tools()
    tools = registry.get_all_tools()
    if not tools:
        raise RuntimeError("Nally tools failed to initialize; refusing to run an agent turn without tools.")
    return tools


class NallyAgent:
    def __init__(
        self, session_id: Optional[str] = None, channel: Optional[str] = None, route_key: Optional[str] = None
    ):
        self.messages: List[dict] = []
        self._session_id = session_id or SESSION_ID
        # Human-facing channel label (e.g. "Telegram voice call"). Explicit
        # instead of sniffed from the session-id prefix, since one shared
        # session ("user:{owner}") is reached from many channels.
        self._channel = channel
        # Per-channel route key for history isolation (Telegram vs Web).
        # Same brain (session_id) but different chat logs.
        self._route_key = route_key or self._session_id
        # Stable abort key. Must equal the session id used by set_abort()
        # (web/ws handlers) so abort flags match the graph's checks. The
        # graph appends a uuid suffix and registers it as an alias back to
        # this value in core/abort.py.
        self._thread_id = self._session_id
        self._lock = threading.Lock()
        self._init_conversation()
        self._load_history()

        # Background memory decay
        threading.Thread(target=self._bg_memory_decay, daemon=True).start()

    def _bg_memory_decay(self):
        """Run memory decay and reset stale facts on startup."""
        try:
            memory_store.reset_stale_facts()
            memory_store.decay_old_memories()
        except Exception as e:
            logger.debug(f"Memory decay failed: {e}")

    def _init_conversation(self):
        """Initialize conversation with system prompt + memory context."""
        user_context = None

        try:
            user_facts = memory_store.get_user_facts()
            if user_facts and user_facts != "No user facts stored yet.":
                user_context = user_facts
        except Exception as e:
            logger.debug(f"Failed to load user facts: {e}")

        try:
            convo_summaries = memory_store.get_conversation_summaries_text(3)
            if convo_summaries:
                if user_context:
                    user_context += f"\n\n{convo_summaries}"
                else:
                    user_context = convo_summaries
        except Exception as e:
            logger.debug(f"Failed to load conversation summaries: {e}")

        try:
            episodes_text = memory_store.get_recent_episodes_text(3)
            if episodes_text:
                if user_context:
                    user_context += f"\n\n{episodes_text}"
                else:
                    user_context = episodes_text
        except Exception as e:
            logger.debug(f"Failed to load recent episodes: {e}")

        system_content = get_system_prompt(user_context=user_context, interface=self._channel or self._session_id)

        self.messages = [{"role": "system", "content": system_content, "cache_control": {"type": "ephemeral"}}]

    def _load_history(self):
        """Load conversation history from database on startup (per-channel)."""
        try:
            saved = memory_store.load_messages(self._session_id, route_key=self._route_key)
            if saved:
                system_msg = self.messages[0] if self.messages else None
                if system_msg:
                    self.messages = [system_msg] + saved
                else:
                    self.messages = saved

                # Prune loaded history immediately to avoid context overflow
                from .context import context_manager

                self.messages = context_manager.prune(self.messages, max_tokens=MAX_CONTEXT_TOKENS)

                logger.debug(f"Loaded {len(saved)} messages from session {self._session_id} route {self._route_key}")
        except Exception as e:
            logger.debug(f"No saved history to load: {e}")

    def _save_history(self):
        """Save conversation history to database on shutdown (per-channel)."""
        try:
            saveable = [m for m in self.messages if m.get("role") != "system"]
            if len(saveable) > 1:
                memory_store.save_messages(saveable, self._session_id, route_key=self._route_key)
                logger.debug(f"Saved {len(saveable)} messages to session {self._session_id} route {self._route_key}")
        except Exception as e:
            logger.debug(f"Failed to save history: {e}")

    def _emit(self, callback: Optional[Callable], event: str, data: dict):
        """Emit a streaming event if callback is provided."""
        if callback:
            try:
                callback(event, data)
            except Exception:
                pass

    def process(self, user_input: str, emit: Optional[Callable] = None) -> str:
        """Process user input and return response."""
        logger.user_input(user_input)
        return self._llm_process(user_input, emit)

    def _llm_process(self, user_input: str, emit: Optional[Callable] = None) -> str:
        """Process using LLM with LangGraph agent loop."""
        from .context import context_manager
        from .graph import run_agent

        start = time.time()

        # Prefix user message with temporal context (no extra messages accumulated)
        now = datetime.now(UTC)
        ts_prefix = f"[Current time: {now.strftime('%Y-%m-%d %H:%M UTC')} | Day: {now.strftime('%A')}]\n\n"

        # ── Input Guardrails ──
        try:
            from .guardrails import guardrail_engine

            input_results = guardrail_engine.check_input(user_input)
            if guardrail_engine.should_block(input_results):
                blocked_msg = "I can't process that request. It appears to be outside my scope."
                for r in input_results:
                    if r.verdict.value == "block":
                        blocked_msg = f"I can't process that request: {r.message}"
                        break
                self.messages.append({"role": "user", "content": ts_prefix + user_input})
                self.messages.append({"role": "assistant", "content": blocked_msg})
                self._save_history()
                return blocked_msg
        except Exception as e:
            logger.debug(f"Input guardrails skipped: {e}")

        self.messages.append({"role": "user", "content": ts_prefix + user_input})

        # Smart context management — single pass
        self.messages = context_manager.prune(self.messages, max_tokens=MAX_CONTEXT_TOKENS)
        self.messages = context_manager.compact(self.messages)

        # Memory and history injections
        self.messages = context_manager.inject_memories(user_input, self.messages)
        self.messages = context_manager.inject_conversation_history(self.messages)

        # Final safety check: prune once more if injections pushed us over
        estimated = context_manager.estimate_tokens(self.messages)
        if estimated > MAX_CONTEXT_TOKENS:
            logger.warning(f"Context over limit after injections ({estimated} tokens), final prune")
            self.messages = context_manager.prune(self.messages, max_tokens=MAX_CONTEXT_TOKENS)

        # Tool registration can overlap startup; the helper waits for the loader
        # lock before exposing a complete tool schema to the model.
        tools = _get_tool_schemas()

        try:
            final_response = run_agent(
                messages=self.messages,
                tools=tools,
                emit=emit,
                max_iterations=MAX_ITERATIONS_PER_TURN,
                thread_id=self._thread_id,
            )

            self.messages.append({"role": "assistant", "content": final_response})

            elapsed = (time.time() - start) * 1000
            logger.nally_response(final_response)
            logger.debug(f"Total response time: {elapsed:.0f}ms")

            self._save_history()
            self._maybe_create_episode(user_input, final_response)

            # Periodic auto-save summary every 20 messages
            if len(self.messages) % 20 == 0 and len(self.messages) > 10:
                self._auto_save_summary()

            return final_response

        except LLMError as e:
            logger.error_with_context("LLM processing failed", e)
            error_msg = e.to_llm_format()
            self.messages.append({"role": "assistant", "content": error_msg})
            self._save_history()
            return error_msg

        except NallyError as e:
            logger.error_with_context("Processing failed", e)
            error_msg = e.to_llm_format()
            self.messages.append({"role": "assistant", "content": error_msg})
            self._save_history()
            return error_msg

        except Exception as e:
            logger.error_with_context("Processing failed", e)
            error_msg = f"I encountered an error: {e!s}"
            self.messages.append({"role": "assistant", "content": error_msg})
            self._save_history()
            return error_msg

    def _maybe_create_episode(self, user_input: str, response: str):
        """Auto-create episode for conversations with substance."""
        if len(self.messages) <= 4:
            return
        try:
            user_msgs = [m["content"] for m in self.messages if m.get("role") == "user"]
            if not user_msgs:
                return
            last_user = user_msgs[-1]
            tools_used = []
            for m in self.messages:
                if isinstance(m, dict) and m.get("role") == "tool":
                    name = m.get("name", "unknown")
                    if name not in tools_used:
                        tools_used.append(name)
            recent_context = " | ".join([m[:60] for m in user_msgs[-3:]])
            memory_store.add_episode(
                topic=last_user[:50],
                what_happened=f"Context: {recent_context}",
                outcome=response[:300] if response else "completed",
                solution=f"Tools: {','.join(tools_used[:5])}" if tools_used else "direct response",
                tags=tools_used[:5],
            )
        except Exception as e:
            logger.debug(f"Episode creation failed: {e}")

    def _auto_save_summary(self):
        """Periodically save conversation summary without clearing."""
        try:
            user_msgs = [m["content"] for m in self.messages if m["role"] == "user"]
            if len(user_msgs) >= 3:
                summary = " | ".join(user_msgs[-5:])
                memory_store.save_conversation(summary=summary, topics=[], message_count=len(user_msgs))
        except Exception:
            pass

    def clear_history(self):
        """Clear conversation history and save summary."""
        self._save_history()

        if len(self.messages) > 2:
            user_msgs = [m["content"] for m in self.messages if m["role"] == "user"]
            if user_msgs:
                summary = " | ".join(user_msgs[-5:])
                try:
                    memory_store.save_conversation(
                        summary=summary,
                        topics=[],
                        message_count=len(user_msgs),
                    )
                    logger.debug("Saved conversation summary")
                except Exception as e:
                    logger.warning(f"Failed to save conversation: {e}")

        logger.debug("Conversation history cleared")
        self._init_conversation()

    def get_history(self) -> List[dict]:
        """Get conversation history."""
        return self.messages


# Lazy singleton — use get_agent() instead of importing agent directly
_agent_instance: Optional[NallyAgent] = None
_agent_lock = threading.Lock()


def get_agent() -> NallyAgent:
    """Get or create the singleton NallyAgent instance (thread-safe).

    Defaults to the owner's shared brain session so CLI turns land in the
    same cross-platform history as web/Telegram/voice (identity, not channel).
    """
    global _agent_instance
    if _agent_instance is None:
        with _agent_lock:
            if _agent_instance is None:
                from .identity import owner_session_id

                _agent_instance = NallyAgent(session_id=owner_session_id(), channel="CLI")
    return _agent_instance
