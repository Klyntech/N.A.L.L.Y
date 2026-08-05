"""Nally Reflector — background reflection engine.

Periodically reviews recent conversations and extracts learnings:
- Conversation summaries
- Episodic memories (what happened, what worked, what failed)
- Semantic patterns (preferences, recurring themes)

Runs as a background thread, triggered periodically or on session end.
"""

import json
import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..utils.logger import logger

# ── Reflection Prompts ────────────────────────────────────

_SUMMARY_PROMPT = """You are Nally, an AI assistant. Summarize this conversation in 2-3 sentences.
Focus on: what the user wanted, what was accomplished, and any notable outcomes.

Conversation:
{conversation}

Respond with ONLY the summary text. No labels, no markdown."""

_EPISODE_PROMPT = """Analyze this conversation and extract ONE key episode (experience worth remembering).

Conversation:
{conversation}

Extract:
1. topic: What was the main thing discussed (2-5 words)
2. what_happened: What Nally did to help (1-2 sentences)
3. outcome: What was the result (success/partial/fail)
4. solution: If there was a problem, how was it solved (1 sentence, or "n/a")
5. tags: 1-3 relevant tags

Output JSON: {{"topic": "...", "what_happened": "...", "outcome": "...", "solution": "...", "tags": ["..."]}}
Output ONLY the JSON. No explanation."""

_PATTERN_PROMPT = """Analyze this conversation for recurring patterns or preferences.

Conversation:
{conversation}

Extract 0-3 patterns. For each, a short phrase describing what Nally learned about the user's preferences, workflow, or style.

Output JSON array: ["pattern 1", "pattern 2"]
Output ONLY the JSON array. If no clear patterns, output []."""

_DAILY_PROMPT = """You are Nally reflecting on the past day. Review these recent conversations:

{recent_conversations}

Generate a daily reflection with:
1. summary: 2-3 sentence overview of the day
2. key_achievements: list of things accomplished (1-3 items)
3. issues_encountered: list of problems or failures (0-3 items)
4. lessons_learned: list of insights about the user or the system (1-3 items)

Output JSON: {{
  "summary": "...",
  "key_achievements": ["..."],
  "issues_encountered": ["..."],
  "lessons_learned": ["..."]
}}
Output ONLY the JSON."""


# ── Reflector Class ───────────────────────────────────────


class Reflector:
    """Background reflection engine that extracts insights from conversations."""

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = 3600  # Default: hourly reflection

    def start(self, interval: int = 3600):
        """Start background reflection thread."""
        if self._running:
            return
        self._interval = interval
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="reflector")
        self._thread.start()
        logger.info(f"Reflector started (interval: {interval}s)")

    def stop(self):
        """Stop background reflection."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Reflector stopped")

    def _loop(self):
        """Background loop that runs reflection periodically."""
        while self._running:
            time.sleep(self._interval)
            try:
                self.daily_reflection()
            except Exception as e:
                logger.error(f"Reflection failed: {e}")

    # ── Public Methods ─────────────────────────────────────

    def daily_reflection(self) -> Optional[Dict[str, Any]]:
        """Run daily reflection on recent conversations."""
        from ..agent.llm import llm
        from ..memory import memory_store

        recent = memory_store.get_recent_conversations(limit=5)
        if not recent:
            return None

        # Build context from recent conversations
        convo_text = "\n\n".join(
            f"[{c['end_date'][:10]}] {c['summary'][:500]}"
            for c in recent if c.get("summary")
        )
        if not convo_text.strip():
            return None

        prompt = _DAILY_PROMPT.format(recent_conversations=convo_text)

        try:
            response = llm.simple_chat(
                user_message=prompt,
                system_prompt="You are a reflection engine. Output only valid JSON.",
            )

            # Parse response
            start = response.find("{")
            end = response.rfind("}") + 1
            if start == -1 or end <= start:
                return None

            data = json.loads(response[start:end])

            # Store as episode
            memory_store.add_episode(
                topic="daily_reflection",
                what_happened=data.get("summary", ""),
                outcome="reflection",
                solution=json.dumps({
                    "achievements": data.get("key_achievements", []),
                    "issues": data.get("issues_encountered", []),
                    "lessons": data.get("lessons_learned", []),
                }),
                tags=["reflection", "daily"],
            )

            # Store lessons as semantic patterns
            for lesson in data.get("lessons_learned", []):
                if lesson:
                    memory_store.add_semantic(lesson, confidence=0.6)

            logger.info(f"Daily reflection complete: {data.get('summary', '')[:100]}")
            return data

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Daily reflection parse failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Daily reflection error: {e}")
            return None

    def reflect_on_conversation(
        self,
        messages: List[Dict[str, Any]],
        session_id: str = "default",
    ) -> Dict[str, Any]:
        """Reflect on a single conversation and extract learnings.

        Called on session end. Returns extracted insights.
        """
        from ..agent.llm import llm
        from ..memory import memory_store

        if len(messages) < 2:
            return {}

        # Build conversation text (last 20 messages max)
        recent = messages[-20:]
        convo_text = "\n".join(
            f"{m.get('role', 'user')}: {str(m.get('content', ''))[:300]}"
            for m in recent
        )

        results = {}

        # 1. Extract conversation summary
        summary = self._extract_summary(llm, convo_text)
        if summary:
            results["summary"] = summary

            # Save conversation summary
            topics = self._extract_topics(llm, convo_text)
            memory_store.save_conversation(
                summary=summary,
                topics=topics,
                message_count=len(messages),
            )

        # 2. Extract episode
        episode = self._extract_episode(llm, convo_text)
        if episode:
            results["episode"] = episode
            memory_store.add_episode(**episode)

        # 3. Extract patterns
        patterns = self._extract_patterns(llm, convo_text)
        if patterns:
            results["patterns"] = patterns
            for pattern in patterns:
                if pattern:
                    memory_store.add_semantic(pattern)

        logger.info(
            f"Conversation reflection: summary={bool(summary)}, "
            f"episode={bool(episode)}, patterns={len(patterns or [])}"
        )
        return results

    # ── Private Helpers ────────────────────────────────────

    def _extract_summary(self, llm, convo_text: str) -> Optional[str]:
        """Extract a conversation summary via LLM."""
        try:
            prompt = _SUMMARY_PROMPT.format(conversation=convo_text)
            response = llm.simple_chat(
                user_message=prompt,
                system_prompt="You are a summarizer. Output only the summary text.",
            )
            return response.strip() if response.strip() else None
        except Exception as e:
            logger.warning(f"Summary extraction failed: {e}")
            return None

    def _extract_episode(self, llm, convo_text: str) -> Optional[Dict[str, Any]]:
        """Extract an episode via LLM."""
        try:
            prompt = _EPISODE_PROMPT.format(conversation=convo_text)
            response = llm.simple_chat(
                user_message=prompt,
                system_prompt="You extract episodes. Output only valid JSON.",
            )

            start = response.find("{")
            end = response.rfind("}") + 1
            if start == -1 or end <= start:
                return None

            data = json.loads(response[start:end])

            # Validate required fields
            if not data.get("topic"):
                return None

            return {
                "topic": data["topic"],
                "what_happened": data.get("what_happened", ""),
                "outcome": data.get("outcome", ""),
                "solution": data.get("solution", ""),
                "tags": data.get("tags", []),
            }

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Episode extraction failed: {e}")
            return None

    def _extract_patterns(self, llm, convo_text: str) -> Optional[List[str]]:
        """Extract semantic patterns via LLM."""
        try:
            prompt = _PATTERN_PROMPT.format(conversation=convo_text)
            response = llm.simple_chat(
                user_message=prompt,
                system_prompt="You extract patterns. Output only a JSON array.",
            )

            start = response.find("[")
            end = response.rfind("]") + 1
            if start == -1 or end <= start:
                return None

            data = json.loads(response[start:end])
            if isinstance(data, list):
                return [str(p) for p in data if p][:3]
            return None

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Pattern extraction failed: {e}")
            return None

    def _extract_topics(self, llm, convo_text: str) -> List[str]:
        """Extract conversation topics (simple heuristic + LLM fallback)."""
        # Quick heuristic: first few nouns/topics from the first user message
        topics = []
        for line in convo_text.split("\n"):
            if line.startswith("user:"):
                words = line[5:].strip().split()[:5]
                topics.extend(w.lower().strip("?.!,") for w in words if len(w) > 3)
                break
        return topics[:3] if topics else ["general"]


# ── Module Singleton ──────────────────────────────────────

reflector = Reflector()
