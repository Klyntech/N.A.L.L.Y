"""Nally Context Manager - Smart context management for 1M+ token windows

Handles:
- Token estimation (count tokens in messages)
- Context compaction (summarize old messages)
- Memory injection (search and inject relevant memories)
- Cost tracking (log token usage)
"""
import json
import re
import time
from typing import List, Dict, Optional, Tuple
from ..utils.logger import logger

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

# Context budget (conservative: 20% of 1M)
MAX_CONTEXT_TOKENS = 200_000

# Recent messages to keep in full
RECENT_MESSAGES = 15

# Compress when more than this many messages
COMPRESSION_THRESHOLD = 30

# Max memories to inject
MAX_MEMORIES = 5


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
        """Truncate large tool outputs and remove oldest non-essential messages"""
        # Step 1: Truncate large tool results
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "tool":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 500:
                    msg["content"] = content[:500] + "\n... [truncated]"

        # Step 2: If still over budget, remove oldest non-system messages
        while self.estimate_tokens(messages) > max_tokens and len(messages) > 10:
            for i, msg in enumerate(messages):
                if isinstance(msg, dict) and msg.get("role") not in ("system",) and 0 < i < len(messages) - 10:
                    messages.pop(i)
                    break
            else:
                break
        return messages

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
        old = messages[1:-(RECENT_MESSAGES)]    # Everything between system and recent

        if len(old) <= 5:
            return messages  # Not worth compressing

        # Build a summary of old messages
        summary = self._summarize_messages(old)

        # Build compacted context
        compacted = [
            system_msg,
            {
                "role": "system",
                "content": f"[Previous conversation context]\n{summary}"
            },
            *recent
        ]

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
        """Create a summary of old messages"""
        parts = []
        topics = set()

        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if role == "user":
                # Extract key points from user messages
                if isinstance(content, str):
                    # Get first 200 chars of each user message
                    snippet = content[:200].strip()
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
                    snippet = content[:100].strip()
                    if snippet:
                        parts.append(f"Nally responded: {snippet}")

            elif role == "tool":
                # Track tool results (very short)
                if isinstance(content, str) and content.strip():
                    snippet = content[:80].strip()
                    if snippet:
                        parts.append(f"Tool result: {snippet}")

        # Build summary
        topic_str = ", ".join(topics) if topics else "general"
        summary_parts = [f"Topics discussed: {topic_str}"]

        # Add key exchanges (limit to keep summary short)
        if parts:
            # Take every other part to get a balanced view
            selected = parts[::2][:10]  # Every other, max 10
            summary_parts.extend(selected)

        return "\n".join(summary_parts)

    def inject_memories(self, query: str, messages: List[Dict]) -> List[Dict]:
        """Search memories and inject relevant ones into context"""
        try:
            from ..memory.store_v2 import memory_v2
            memories = memory_v2.recall(search=query, min_confidence=0.5, limit=MAX_MEMORIES)
        except Exception:
            return messages

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
        messages.insert(inject_index, {
            "role": "system",
            "content": f"[Relevant memories]\n{memory_text}"
        })

        self._stats["memories_injected"] += 1
        logger.debug(f"Injected {len(memories)} memories into context")

        return messages

    def inject_conversation_history(self, messages: List[Dict]) -> List[Dict]:
        """Inject recent conversation summaries"""
        try:
            from ..memory.store_v2 import memory_v2
            summaries_text = memory_v2.get_conversation_summaries_text(3)
        except Exception:
            return messages

        if not summaries_text:
            return messages

        # Inject after system prompt
        messages.insert(1, {
            "role": "system",
            "content": summaries_text
        })

        return messages

    def track_usage(self, input_tokens: int, output_tokens: int):
        """Track token usage for cost estimation"""
        self._stats["total_requests"] += 1
        self._stats["total_tokens_in"] += input_tokens
        self._stats["total_tokens_out"] += output_tokens

    def get_stats(self) -> Dict:
        """Get context management statistics"""
        return {
            **self._stats,
            "avg_tokens_per_request": (
                self._stats["total_tokens_in"] // max(1, self._stats["total_requests"])
            ),
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
