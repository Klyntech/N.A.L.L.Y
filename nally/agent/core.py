"""Nally Core Agent - The Brain"""
import json
import os
import re
import time
import threading
from typing import List, Optional, Callable

from ..config import get_system_prompt, SESSION_ID, ACTIVE_MODEL, MAX_ITERATIONS_PER_TURN
from ..core.errors import NallyError, LLMError, ToolError
from ..memory.store_v2 import memory_v2 as memory_store, memory_tools_v2
from ..utils.logger import logger
from .router import matcher


def _strip_emojis(text: str) -> str:
    """Remove emojis and special unicode symbols from text"""
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001f926-\U0001f937"
        "\U00010000-\U0010ffff"
        "\u200d"
        "\ufe0f"
        "\u2640-\u2642"
        "\u2600-\u2B55"
        "\u23cf"
        "\u23e9"
        "\u231a"
        "\u3030"
        "\u2934"
        "\u2935"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()


def _capitalize_sentences(text: str) -> str:
    """Capitalize the first letter of every sentence."""
    return re.sub(
        r'(^|[.!?]\s+)([a-z])',
        lambda m: m.group(1) + m.group(2).upper(),
        text,
    )


_TIME_SENSITIVE_PATTERNS = [
    r"this\s+(season|year|month|week|weekend)",
    r"(20\d{2})\s*[-–]\s*(20\d{2})",
    r"(match|matches|result|score|fixture|standing|league|table|rank)",
    r"(news|latest|recent|current|update)",
    r"(price|stock|rate|weather|temperature|forecast)",
    r"(who\s+won|final\s+score)",
    r"(upcoming|next|schedule)",
    r"(release\s+date|when\s+does)",
]


def _needs_web_search(query: str) -> bool:
    """Check if query looks time-sensitive and needs web search context."""
    q = query.lower()
    return any(re.search(p, q) for p in _TIME_SENSITIVE_PATTERNS)


def _extract_topics(user_msgs: List[str]) -> List[str]:
    """Extract conversation topics from user messages."""
    topic_keywords = {
        "deployment": ["deploy", "render", "server", "hosting"],
        "coding": ["code", "function", "class", "import", "api"],
        "memory": ["memory", "remember", "recall", "forget"],
        "frontend": ["widget", "ui", "frontend", "css", "html"],
        "debugging": ["fix", "bug", "error", "issue"],
        "devops": ["docker", "ci", "pipeline", "git"],
        "ai": ["agent", "llm", "model", "ai"],
    }
    topics = []
    for msg in user_msgs[-10:]:
        msg_lower = msg.lower()
        for topic, keywords in topic_keywords.items():
            if any(w in msg_lower for w in keywords) and topic not in topics:
                topics.append(topic)
    return topics[:3] or ["general"]


class NallyAgent:
    def __init__(self):
        self.messages: List[dict] = []
        self._thread_id = f"nally-main-{SESSION_ID}"
        self._session_id = SESSION_ID
        self._lock = threading.Lock()
        self._init_conversation()
        self._load_history()

        # Background memory decay
        threading.Thread(target=self._bg_memory_decay, daemon=True).start()

    def _bg_memory_decay(self):
        """Run memory decay in background on startup."""
        try:
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

        system_content = get_system_prompt(user_context=user_context)

        self.messages = [
            {"role": "system", "content": system_content, "cache_control": {"type": "ephemeral"}}
        ]

    def _load_history(self):
        """Load conversation history from database on startup."""
        try:
            saved = memory_store.load_messages(self._session_id)
            if saved:
                system_msg = self.messages[0] if self.messages else None
                if system_msg:
                    self.messages = [system_msg] + saved
                else:
                    self.messages = saved
                logger.debug(f"Loaded {len(saved)} messages from session {self._session_id}")
        except Exception as e:
            logger.debug(f"No saved history to load: {e}")

    def _save_history(self):
        """Save conversation history to database on shutdown."""
        try:
            if len(self.messages) > 1:
                memory_store.save_messages(self.messages, self._session_id)
                logger.debug(f"Saved {len(self.messages)} messages to session {self._session_id}")
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
        start = time.time()

        # Skip local patterns for compound requests and research commands
        compound_indicators = [" and ", " then ", " also ", " plus ", " with "]
        research_commands = ["deep research", "quick search", "read article", "list reports"]
        is_compound = any(ind in user_input.lower() for ind in compound_indicators)
        is_research = any(cmd in user_input.lower() for cmd in research_commands)

        if not is_compound and not is_research:
            handler = matcher.match(user_input)
            if handler:
                try:
                    result = handler()
                except NallyError as e:
                    logger.error_with_context("Local handler error", e)
                    result = e.to_llm_format()
                except Exception as e:
                    logger.error_with_context("Local handler error", e)
                    result = f"Error: {str(e)}"

                if result == "__EXIT__":
                    self._save_history()
                    return "__EXIT__"

                elapsed = (time.time() - start) * 1000
                result = _capitalize_sentences(_strip_emojis(result))
                logger.nally_response(result)
                logger.debug(f"Response time: {elapsed:.0f}ms (local)")
                self._save_history()
                return result

        return self._llm_process(user_input, emit)

    def _llm_process(self, user_input: str, emit: Optional[Callable] = None) -> str:
        """Process using LLM with LangGraph agent loop."""
        from .graph import run_agent
        from .context import context_manager
        from ..tools.registry import registry

        start = time.time()

        self.messages.append({"role": "user", "content": user_input})

        # Skill activation (Level 2): check if a skill matches this request
        try:
            from ..skills.loader import activate_skill
            from ..skills.registry import skill_registry
            from ..tools.permissions import gate as perm_gate
            if not skill_registry._loaded:
                skill_registry.load()
            matched = skill_registry.find_by_intent(user_input)
            if matched:
                skill_body = skill_registry.activate(matched[0])
                skill_obj = skill_registry.get(matched[0])
                if skill_body:
                    self.messages.append({
                        "role": "system",
                        "content": f"[SKILL ACTIVATED: {matched[0]}]\n\n{skill_body}\n\nFollow these instructions for this task."
                    })
                    # Grant skill's allowed-tools temporarily
                    if skill_obj and skill_obj.allowed_tools:
                        perm_gate.set_skill_overrides(matched[0], skill_obj.allowed_tools)
        except Exception:
            pass  # Skills not available

        # Smart context management
        self.messages = context_manager.compact(self.messages)
        self.messages = context_manager.inject_memories(user_input, self.messages)

        # Build tool set
        try:
            from ..tools.filter import tool_filter
            if not tool_filter._ready:
                tool_filter.build_index(registry.tools)
            tools = tool_filter.select(user_input)
        except ImportError:
            tools = [t.to_openai_schema() for t in registry.tools.values()]

        # Auto-search for time-sensitive queries — inject fresh web data
        # so the LLM sees real results regardless of whether it calls web_search
        if _needs_web_search(user_input):
            try:
                from ..tools.websearch import WebSearch
                ws = WebSearch()
                results = ws.execute(query=user_input, num_results=3)
                if results:
                    from langchain_core.messages import SystemMessage
                    self.messages.insert(1, SystemMessage(
                        content=f"[Auto-searched web for '{user_input}']:\n{results}"
                    ))
            except Exception:
                pass  # fallback to LLM's own knowledge

        try:
            final_response = run_agent(
                messages=self.messages,
                tools=tools,
                emit=emit,
                max_iterations=MAX_ITERATIONS_PER_TURN,
                thread_id=self._thread_id,
            )

            final_response = _capitalize_sentences(_strip_emojis(final_response))
            self.messages.append({"role": "assistant", "content": final_response})

            # Clear skill overrides after task completion
            try:
                from ..tools.permissions import gate as perm_gate
                perm_gate.clear_all_skill_overrides()
            except Exception:
                pass

            elapsed = (time.time() - start) * 1000
            logger.nally_response(final_response)
            logger.debug(f"Total response time: {elapsed:.0f}ms")

            self._save_history()
            self._maybe_create_episode(user_input, final_response)

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
            error_msg = f"I encountered an error: {str(e)}"
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
            memory_store.add_episode(
                topic=last_user[:50],
                what_happened=f"User asked: {last_user[:100]}",
                outcome=response[:200] if response else "completed",
                solution=",".join(tools_used[:5]) if tools_used else "direct response",
                tags=tools_used[:3],
            )
        except Exception as e:
            logger.debug(f"Episode creation failed: {e}")

    def clear_history(self):
        """Clear conversation history and save summary."""
        self._save_history()

        if len(self.messages) > 2:
            user_msgs = [m["content"] for m in self.messages if m["role"] == "user"]
            if user_msgs:
                summary = " | ".join(user_msgs[-5:])
                topics = _extract_topics(user_msgs)
                try:
                    memory_store.save_conversation(
                        summary=summary,
                        topics=topics,
                        message_count=len(user_msgs),
                    )
                    logger.debug(f"Saved conversation: {topics}")
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
    """Get or create the singleton NallyAgent instance (thread-safe)."""
    global _agent_instance
    if _agent_instance is None:
        with _agent_lock:
            if _agent_instance is None:
                _agent_instance = NallyAgent()
    return _agent_instance
