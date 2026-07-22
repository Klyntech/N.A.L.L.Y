"""Nally Core Agent - The Brain"""
import atexit
import json
import os
import re
import time
from typing import List, Optional, Callable
from .llm import llm
from .router import matcher
from .context import context_manager
from ..tools.registry import registry
from ..config import SYSTEM_PROMPT, MAX_CONVERSATION_HISTORY
from ..memory.store_v2 import memory_v2
from ..utils.logger import logger

# Stubs for modules not copied during migration
try:
    from ..tools.filter import tool_filter
except ImportError:
    class _StubFilter:
        _ready = False
        def build_index(self, tools): pass
        def select(self, query, **kw): return []
    tool_filter = _StubFilter()


# Fixed session ID for persistent conversation history
SESSION_ID = os.getenv("NALLY_SESSION", "default")


def strip_emojis(text: str) -> str:
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
        flags=re.UNICODE
    )
    return emoji_pattern.sub("", text).strip()


class NallyAgent:
    def __init__(self):
        self.messages: List[dict] = []
        self.system_prompt = SYSTEM_PROMPT
        # Use fixed thread_id for checkpoint persistence across restarts
        self._thread_id = f"nally-main-{SESSION_ID}"
        self._session_id = SESSION_ID
        self._init_conversation()
        self._load_history()
        
        # Register shutdown hook to save history
        atexit.register(self._save_history)
        
        # Run memory decay on startup in background thread
        def _bg_decay():
            try:
                memory_v2.decay_old_memories()
            except Exception:
                pass
        import threading
        threading.Thread(target=_bg_decay, daemon=True).start()

    def _init_conversation(self):
        """Initialize conversation with system prompt + memory context"""
        system_content = self.system_prompt

        # Inject recent conversation summaries
        try:
            convo_summaries = memory_v2.get_conversation_summaries_text(3)
            if convo_summaries:
                system_content += f"\n\n{convo_summaries}"
        except Exception:
            pass

        # Inject user facts from memory
        try:
            user_facts = memory_v2.get_user_facts()
            if user_facts and user_facts != "No user facts stored yet.":
                system_content += f"\n\nKNOWN USER FACTS:\n{user_facts}"
        except Exception:
            pass

        self.messages = [
            {"role": "system", "content": system_content, "cache_control": {"type": "ephemeral"}}
        ]

    def _load_history(self):
        """Load conversation history from database on startup"""
        try:
            saved = memory_v2.load_messages(self._session_id)
            if saved:
                # Keep the system message, append saved history
                system_msg = self.messages[0] if self.messages else None
                if system_msg:
                    self.messages = [system_msg] + saved
                else:
                    self.messages = saved
                logger.debug(f"Loaded {len(saved)} messages from session {self._session_id}")
        except Exception as e:
            logger.debug(f"No saved history to load: {e}")

    def _save_history(self):
        """Save conversation history to database on shutdown"""
        try:
            if len(self.messages) > 1:  # More than just system message
                memory_v2.save_messages(self.messages, self._session_id)
                logger.debug(f"Saved {len(self.messages)} messages to session {self._session_id}")
        except Exception as e:
            logger.debug(f"Failed to save history: {e}")

    def _emit(self, callback: Optional[Callable], event: str, data: dict):
        """Emit a streaming event if callback is provided"""
        if callback:
            try:
                callback(event, data)
            except Exception:
                pass

    def process(self, user_input: str, emit: Optional[Callable] = None) -> str:
        """Process user input and return response"""
        logger.user_input(user_input)
        start = time.time()

        # Personal fact extraction only happens when user explicitly asks Nally to remember something
        # (handled by remember tool, not auto-extracted from every message)

        # Skip local patterns for compound requests AND research commands
        compound_indicators = [' and ', ' then ', ' also ', ' plus ', ' with ']
        research_commands = ['deep research', 'quick search', 'read article', 'list reports']
        is_compound = any(indicator in user_input.lower() for indicator in compound_indicators)
        is_research = any(cmd in user_input.lower() for cmd in research_commands)

        if not is_compound and not is_research:
            # Try local pattern matching first (instant)
            handler = matcher.match(user_input)
            if handler:
                try:
                    result = handler()
                except Exception as e:
                    logger.error_with_context("Local handler error", e)
                    result = f"Error: {str(e)}"

                if result == "__EXIT__":
                    self._save_history()
                    return "__EXIT__"

                elapsed = (time.time() - start) * 1000
                result = strip_emojis(result)
                logger.nally_response(result)
                logger.debug(f"Response time: {elapsed:.0f}ms (local)")
                self._save_history()
                return result

        # Fall back to LLM (handles compound requests and everything else)
        return self._llm_process(user_input, emit)

    def _llm_process(self, user_input: str, emit: Optional[Callable] = None) -> str:
        """Process using LLM with LangGraph agent loop"""
        from .graph import run_agent
        start = time.time()

        # Add user message
        self.messages.append({"role": "user", "content": user_input})

        # Smart context management
        self.messages = context_manager.compact(self.messages)

        # Inject relevant memories on demand
        self.messages = context_manager.inject_memories(user_input, self.messages)

        # Build tool filter index on first use
        if not tool_filter._ready:
            tool_filter.build_index(registry.tools)

        # Get filtered tools for this query
        tools = tool_filter.select(user_input)

        try:
            # Run the LangGraph agent loop
            final_response = run_agent(
                messages=self.messages,
                tools=tools,
                emit=emit,
                max_iterations=5,
                thread_id=self._thread_id
            )

            # Strip emojis from response
            final_response = strip_emojis(final_response)

            # Add assistant response to history
            self.messages.append({"role": "assistant", "content": final_response})

            elapsed = (time.time() - start) * 1000
            logger.nally_response(final_response)
            logger.debug(f"Total response time: {elapsed:.0f}ms")

            # Save history after each interaction
            self._save_history()

            # Auto-episode creation for conversations with substance
            if len(self.messages) > 4:
                try:
                    user_msgs = [m["content"] for m in self.messages if m.get("role") == "user"]
                    if user_msgs:
                        last_user = user_msgs[-1]
                        topic = last_user[:50]
                        tools_used = []
                        for m in self.messages:
                            if isinstance(m, dict) and m.get("role") == "tool":
                                name = m.get("name", "unknown")
                                if name not in tools_used:
                                    tools_used.append(name)
                        outcome = final_response[:200] if final_response else "completed"
                        memory_v2.add_episode(
                            topic=topic,
                            what_happened=f"User asked: {last_user[:100]}",
                            outcome=outcome,
                            solution=",".join(tools_used[:5]) if tools_used else "direct response",
                            tags=tools_used[:3]
                        )
                except Exception:
                    pass

            return final_response

        except Exception as e:
            error_msg = str(e)
            if "rate_limit" in error_msg or "429" in error_msg:
                error_msg = "Rate limit reached. Please wait a minute and try again."
            else:
                error_msg = f"I encountered an error: {error_msg}"
            logger.error_with_context("LLM processing failed", e)
            self.messages.append({"role": "assistant", "content": error_msg})
            self._save_history()
            return error_msg

    def clear_history(self):
        """Clear conversation history and save summary"""
        # Save current history first
        self._save_history()
        
        if len(self.messages) > 2:
            user_msgs = [m["content"] for m in self.messages if m["role"] == "user"]
            if user_msgs:
                # Create summary from all user messages
                summary = " | ".join(user_msgs[-5:])
                topics = []
                for msg in user_msgs:
                    msg_lower = msg.lower()
                    if any(w in msg_lower for w in ["deploy", "render", "server"]):
                        topics.append("deployment")
                    elif any(w in msg_lower for w in ["code", "function", "class", "import"]):
                        topics.append("coding")
                    elif any(w in msg_lower for w in ["memory", "remember", "recall"]):
                        topics.append("memory")
                    elif any(w in msg_lower for w in ["widget", "ui", "frontend"]):
                        topics.append("frontend")
                    elif any(w in msg_lower for w in ["fix", "bug", "error"]):
                        topics.append("debugging")
                topics = list(set(topics))[:3] or ["general"]

                try:
                    memory_v2.save_conversation(
                        summary=summary,
                        topics=topics,
                        message_count=len(user_msgs)
                    )
                    logger.debug(f"Saved conversation: {topics}")
                except Exception as e:
                    logger.warning(f"Failed to save conversation: {e}")
        logger.debug("Conversation history cleared")
        self._init_conversation()

    def get_history(self) -> List[dict]:
        """Get conversation history"""
        return self.messages


agent = NallyAgent()
