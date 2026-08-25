"""Group Chat Orchestration — multi-perspective analysis.

Pattern from AutoGen: star topology with LLM-driven speaker selection.
Multiple agents analyze a problem from different angles, iterate on
each other's work, and synthesize a final answer.

Use case: "Help me decide on a car purchase" → research agent, budget
agent, critic agent iterate together.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nally.group_chat")


@dataclass
class ChatMessage:
    """A message in the group chat."""
    speaker: str
    content: str
    round_num: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "speaker": self.speaker,
            "content": self.content[:500],
            "round": self.round_num,
            "timestamp": self.timestamp,
        }


@dataclass
class GroupChatResult:
    """Result of a group chat session."""
    topic: str
    messages: List[ChatMessage]
    synthesis: str
    participants: List[str]
    rounds: int
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "messages": [m.to_dict() for m in self.messages],
            "synthesis": self.synthesis[:1000],
            "participants": self.participants,
            "rounds": self.rounds,
            "duration_ms": self.duration_ms,
        }


class GroupChatOrchestrator:
    """Orchestrates multi-agent group chat discussions.

    Flow:
    1. Assemble agents (personas) for the discussion
    2. Each agent speaks in turn (round-robin or LLM-selected)
    3. Each agent can review and build on previous agents' responses
    4. After N rounds, synthesize a final answer
    """

    def __init__(self, llm_call_fn: Callable):
        self._llm_call = llm_call_fn
        self._max_rounds = 3
        self._max_messages_per_round = 5

    def run(
        self,
        topic: str,
        participants: List[Dict[str, str]],
        context: str = "",
        max_rounds: int = 3,
    ) -> GroupChatResult:
        """Run a group chat discussion.

        Args:
            topic: The topic to discuss
            participants: List of {"name": ..., "role": ..., "goal": ...}
            context: Additional context for the discussion
            max_rounds: Maximum discussion rounds

        Returns:
            GroupChatResult with all messages and synthesis
        """
        start_time = time.time()
        messages: List[ChatMessage] = []
        participant_names = [p.get("name", f"Agent_{i}") for i, p in enumerate(participants)]

        for round_num in range(1, max_rounds + 1):
            logger.info(f"Group chat round {round_num}/{max_rounds}")

            for participant in participants:
                name = participant.get("name", "Unknown")
                role = participant.get("role", "")
                goal = participant.get("goal", "")

                # Build context for this speaker
                prior_messages = [f"{m.speaker}: {m.content[:300]}" for m in messages[-10:]]
                prior_context = "\n".join(prior_messages) if prior_messages else "No prior messages."

                prompt = (
                    f"You are {name}, a {role}.\n"
                    f"Goal: {goal}\n\n"
                    f"Topic: {topic}\n"
                    f"Context: {context}\n\n"
                    f"Prior discussion:\n{prior_context}\n\n"
                    f"Share your perspective on this topic. Be specific and concise."
                )

                try:
                    response = self._llm_call(
                        messages=[
                            {"role": "system", "content": f"You are {name}. {role}"},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.7,
                    )
                    if response and not response.startswith("Error"):
                        msg = ChatMessage(
                            speaker=name,
                            content=response[:1000],
                            round_num=round_num,
                        )
                        messages.append(msg)
                except Exception as e:
                    logger.warning(f"Group chat: {name} failed: {e}")

        # Synthesize
        synthesis = self._synthesize(topic, messages, participant_names)

        duration = int((time.time() - start_time) * 1000)
        return GroupChatResult(
            topic=topic,
            messages=messages,
            synthesis=synthesis,
            participants=participant_names,
            rounds=max_rounds,
            duration_ms=duration,
        )

    def _synthesize(self, topic: str, messages: List[ChatMessage], participants: List[str]) -> str:
        """Synthesize all discussion into a final answer."""
        discussion = "\n".join(f"{m.speaker} (Round {m.round_num}): {m.content[:400]}" for m in messages)

        prompt = (
            f"Topic: {topic}\n\n"
            f"Discussion between {', '.join(participants)}:\n\n"
            f"{discussion}\n\n"
            f"Synthesize this discussion into a clear, comprehensive answer. "
            f"Include key points of agreement, disagreement, and the final recommendation."
        )

        try:
            response = self._llm_call(
                messages=[
                    {"role": "system", "content": "You are synthesizing a group discussion into a final answer."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
            )
            return response or "Unable to synthesize discussion."
        except Exception as e:
            logger.warning(f"Group chat synthesis failed: {e}")
            return "Synthesis failed. See individual perspectives above."
