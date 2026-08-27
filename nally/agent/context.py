"""Nally Context Manager - Smart context management for 1M+ token windows

Handles:
- Token estimation (count tokens in messages)
- Context compaction (summarize old messages)
- Memory injection (search and inject relevant memories)
- Cost tracking (log token usage)
"""

import json
import re
from datetime import date
from typing import Dict, List

from ..utils.logger import logger

_STOPWORDS = frozenset({
    "the", "is", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "it", "this", "that", "are", "was", "were", "be",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "shall", "not", "no", "if", "then", "than", "so",
    "just", "about", "what", "when", "where", "how", "who", "which", "there",
    "here", "now", "also", "very", "too", "my", "your", "its", "our", "their",
    "me", "him", "her", "us", "them", "you", "he", "she", "we", "they", "i",
})

# Try tiktoken for accurate token counting, fall back to char estimation
try:
    import tiktoken

    _enc = tiktoken.encoding_for_model("gpt-4")

    def _count_tokens(text):
        return len(_enc.encode(str(text)))
except Exception:
    _enc = None

    def _count_tokens(text):
        return len(str(text)) // 4


# Import from config (single source of truth)
from ..config import (
    CONTEXT_COMPRESSION_THRESHOLD as COMPRESSION_THRESHOLD,
)
from ..config import (
    CONTEXT_MAX_TOKENS as MAX_CONTEXT_TOKENS,
)
from ..config import (
    CONTEXT_RECENT_MESSAGES as RECENT_MESSAGES,
)
from ..config import (
    DAILY_TOKEN_BUDGET,
)
from ..config import (
    MAX_MEMORIES_TO_INJECT as MAX_MEMORIES,
)


class ContextManager:
    """Smart context management for long conversations"""

    def __init__(self):
        self._stats = {
            "total_requests": 0,
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "compactions": 0,
            "memories_injected": 0,
        }
        # Daily token budget tracking
        self._budget_date: date = date.today()
        self._daily_tokens: int = 0

    def estimate_tokens(self, messages: List[Dict]) -> int:
        """Estimate token count for a list of messages"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += _count_tokens(content)
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                total += _count_tokens(json.dumps(tool_calls))
        return total

    def prune(self, messages: List[Dict], max_tokens: int = 150000) -> List[Dict]:
        """Truncate large tool outputs and remove oldest non-essential messages.

        Preserves: system messages, user messages, and recent messages.
        Only removes old assistant/tool messages when over budget.

        Non-mutating on tool content truncation — returns a shallow copy with
        truncated tool messages so the original list's evidence is not destroyed
        (fixes Phase 0 truncation cascade: 50k→2k→1.5k→500).
        Truncation cap raised from 1500 to 8000 to preserve error signals.
        """
        # Step 1: Truncate large tool results — work on a shallow copy
        # so callers' original evidence is preserved for receipts/verifier.
        import copy as _copy

        pruned = []
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "tool":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 8000:
                    new_msg = _copy.copy(msg)
                    new_msg["content"] = content[:8000] + f"\n... [truncated {len(content)} → 8000 chars]"
                    pruned.append(new_msg)
                else:
                    pruned.append(msg)
            else:
                pruned.append(msg)

        # Step 2: If still over budget, remove oldest non-system, non-user messages
        # NEVER remove user messages — they contain the original request
        while self.estimate_tokens(pruned) > max_tokens and len(pruned) > 10:
            removed = False
            for i, msg in enumerate(pruned):
                role = msg.get("role") if isinstance(msg, dict) else None
                # Only remove old assistant or tool messages, never user or system
                if role in ("assistant", "tool") and 0 < i < len(pruned) - 10:
                    pruned.pop(i)
                    removed = True
                    break
            if not removed:
                break
        return pruned

    def compact(self, messages: List[Dict]) -> List[Dict]:
        """Smart context compaction - summarize old messages, keep recent in full"""
        if len(messages) <= RECENT_MESSAGES + 2:
            return messages  # Not enough to compress

        # Token-budget gate: skip compaction if under budget and under message limit
        total_tokens = self.estimate_tokens(messages)
        if total_tokens < MAX_CONTEXT_TOKENS * 0.8 and len(messages) <= COMPRESSION_THRESHOLD:
            return messages

        system_msg = messages[0]
        recent = messages[-(RECENT_MESSAGES):]  # Last N messages
        old = messages[1:-(RECENT_MESSAGES)]  # Everything between system and recent

        if len(old) <= 5:
            return messages  # Not worth compressing

        # Build a summary of old messages
        summary = self._summarize_messages(old)

        # Build compacted context
        compacted = [system_msg, {"role": "system", "content": f"[Previous conversation context]\n{summary}"}, *recent]

        # Log compaction
        old_tokens = self.estimate_tokens(messages)
        new_tokens = self.estimate_tokens(compacted)
        saved = old_tokens - new_tokens

        if saved > 100:
            self._stats["compactions"] += 1
            logger.debug(
                f"Context compacted: {old_tokens} → {new_tokens} tokens "
                f"(saved {saved} tokens, {len(old)} messages → summary)"
            )

        return compacted

    def _summarize_messages(self, messages: List[Dict]) -> str:
        """Create a summary of old messages.
        
        Preserves full user messages (they contain the original request context).
        Summarizes assistant responses and tool results more aggressively.
        """
        parts = []
        topics = set()

        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if role == "user":
                # Keep FULL user messages — they're the most important context
                if isinstance(content, str):
                    snippet = content.strip()
                    if snippet:
                        parts.append(f"User asked: {snippet}")

                        # Track topics
                        content_lower = content.lower()
                        if any(w in content_lower for w in ["deploy", "render", "server"]):
                            topics.add("deployment")
                        elif any(w in content_lower for w in ["code", "function", "class"]):
                            topics.add("coding")
                        elif any(w in content_lower for w in ["memory", "remember"]):
                            topics.add("memory")
                        elif any(w in content_lower for w in ["widget", "ui", "frontend"]):
                            topics.add("frontend")
                        elif any(w in content_lower for w in ["fix", "bug", "error"]):
                            topics.add("debugging")

            elif role == "assistant":
                # Track tool calls
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            func = tc.get("function", {})
                            name = func.get("name", "unknown")
                            parts.append(f"Used tool: {name}")

                # Track assistant responses (shorter)
                if isinstance(content, str) and content.strip():
                    snippet = content[:200].strip()
                    if snippet:
                        parts.append(f"Nally responded: {snippet}")

            elif role == "tool":
                # Track tool results (very short)
                if isinstance(content, str) and content.strip():
                    snippet = content[:150].strip()
                    if snippet:
                        parts.append(f"Tool result: {snippet}")

        # Build summary
        topic_str = ", ".join(topics) if topics else "general"
        summary_parts = [f"Topics discussed: {topic_str}"]

        # Add key exchanges — user messages always included, assistant/tool sampled
        if parts:
            user_parts = [p for p in parts if p.startswith("User asked:")]
            other_parts = [p for p in parts if not p.startswith("User asked:")]
            # All user messages, every other assistant/tool message (max 15)
            selected = user_parts + other_parts[::2][:15]
            summary_parts.extend(selected)

        return "\n".join(summary_parts)

    def inject_memories(self, query: str, messages: List[Dict]) -> List[Dict]:
        """Search memories and inject relevant ones into context"""
        try:
            from ..memory import memory_store

            memories = memory_store.recall(search=query, min_confidence=0.5, limit=MAX_MEMORIES)
        except Exception as e:
            logger.debug(f"Memory recall failed: {e}")
            return messages

        # Also search with extracted keywords (skip stopwords)
        try:
            keywords = [w for w in re.split(r'[^a-zA-Z0-9_]+', query) if len(w) >= 3 and w.lower() not in _STOPWORDS]
            if keywords:
                keyword_query = " ".join(keywords[:5])
                kw_mems = memory_store.recall(search=keyword_query, min_confidence=0.5, limit=5)
                if kw_mems and isinstance(kw_mems, dict):
                    if not memories:
                        memories = {}
                    for k, v in kw_mems.items():
                        if k not in memories:
                            memories[k] = v
        except Exception:
            pass

        # Always inject high-priority category memories (projects, auto_facts)
        try:
            from ..memory import memory_store as mv2
            for cat in ("project", "auto_fact"):
                cat_mems = mv2.recall(category=cat, min_confidence=0.5, limit=5)
                if cat_mems and isinstance(cat_mems, dict):
                    if not memories:
                        memories = {}
                    for k, v in cat_mems.items():
                        if k not in memories:
                            memories[k] = v
        except Exception:
            pass

        if not memories or not isinstance(memories, dict) or len(memories) == 0:
            return messages

        # Format memories
        memory_lines = []
        for k, v in list(memories.items())[:MAX_MEMORIES]:
            memory_lines.append(f"- {k}: {v}")

        memory_text = "\n".join(memory_lines)

        # Find where to inject (after system prompt, before user messages)
        inject_index = 1
        for i, msg in enumerate(messages):
            if msg.get("role") == "user":
                inject_index = i
                break

        # Inject memory context
        messages.insert(inject_index, {"role": "system", "content": f"[Relevant memories]\n{memory_text}"})

        self._stats["memories_injected"] += 1
        logger.debug(f"Injected {len(memories)} memories into context")

        return messages

    def inject_conversation_history(self, messages: List[Dict]) -> List[Dict]:
        """Inject recent conversation summaries"""
        try:
            from ..memory import memory_store

            summaries_text = memory_store.get_conversation_summaries_text(3)
        except Exception as e:
            logger.debug(f"Conversation history injection failed: {e}")
            return messages

        if not summaries_text:
            return messages

        # Inject after system prompt
        messages.insert(1, {"role": "system", "content": summaries_text})

        return messages

    def track_usage(self, input_tokens: int, output_tokens: int):
        """Track token usage for cost estimation and daily budget."""
        self._stats["total_requests"] += 1
        self._stats["total_tokens_in"] += input_tokens
        self._stats["total_tokens_out"] += output_tokens

        # Daily budget tracking — auto-reset at midnight UTC
        today = date.today()
        if today != self._budget_date:
            self._budget_date = today
            self._daily_tokens = 0
            logger.info("Daily token budget reset")

        used = input_tokens + output_tokens
        self._daily_tokens += used

    def check_budget(self) -> bool:
        """Return True if within daily budget, False if exceeded."""
        if DAILY_TOKEN_BUDGET <= 0:
            return True  # Unlimited
        # Check date rollover
        today = date.today()
        if today != self._budget_date:
            self._budget_date = today
            self._daily_tokens = 0
        return self._daily_tokens < DAILY_TOKEN_BUDGET

    @property
    def budget_exceeded(self) -> bool:
        """Return True if daily token budget is exceeded."""
        return not self.check_budget()

    def get_stats(self) -> Dict:
        """Get context management statistics"""
        return {
            **self._stats,
            "avg_tokens_per_request": (self._stats["total_tokens_in"] // max(1, self._stats["total_requests"])),
            "daily_tokens": self._daily_tokens,
            "daily_token_budget": DAILY_TOKEN_BUDGET,
            "daily_budget_remaining": max(0, DAILY_TOKEN_BUDGET - self._daily_tokens) if DAILY_TOKEN_BUDGET > 0 else -1,
        }

    def get_context_preview(self, messages: List[Dict]) -> Dict:
        """Get a preview of what the context will look like"""
        tokens = self.estimate_tokens(messages)
        recent = len(messages[-RECENT_MESSAGES:]) if len(messages) > RECENT_MESSAGES else len(messages) - 1
        compressed = max(0, len(messages) - 1 - RECENT_MESSAGES)

        return {
            "total_tokens": tokens,
            "within_budget": tokens <= MAX_CONTEXT_TOKENS,
            "budget_remaining": MAX_CONTEXT_TOKENS - tokens,
            "recent_messages": recent,
            "compressed_messages": compressed,
            "would_compress": len(messages) > COMPRESSION_THRESHOLD,
        }


# Singleton
context_manager = ContextManager()
