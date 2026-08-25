"""Handoffs — clean context rewriting for sub-agent delegation.

When Nally delegates to a sub-agent, the sub-agent gets a focused context
window with only the information relevant to its specific goal, not the
full conversation history.

Pattern from OpenAI Agents SDK: handoffs rewrite context so each
specialist receives only what they need.
"""

import re
from typing import Any, Dict, List, Optional


def rewrite_context(
    goal: str,
    full_context: str,
    conversation_messages: Optional[List[Dict]] = None,
    max_tokens: int = 4000,
) -> str:
    """Rewrite context to give sub-agent only what's relevant to its goal.

    Extracts:
    1. The original user request that triggered this delegation
    2. Any relevant prior findings or tool results
    3. Constraints or requirements mentioned in the conversation

    Strips:
    - Irrelevant conversation turns
    - Tool call details not related to the goal
    - Previous sub-agent results for different goals
    """
    if not full_context and not conversation_messages:
        return goal

    parts = []

    # 1. Extract the triggering request
    if conversation_messages:
        triggering_request = _extract_triggering_request(conversation_messages, goal)
        if triggering_request:
            parts.append(f"Original request: {triggering_request}")

    # 2. Extract relevant prior findings
    if conversation_messages:
        relevant_findings = _extract_relevant_findings(conversation_messages, goal)
        if relevant_findings:
            parts.append(f"Prior findings:\n{relevant_findings}")

    # 3. Extract constraints
    if conversation_messages:
        constraints = _extract_constraints(conversation_messages)
        if constraints:
            parts.append(f"Constraints: {constraints}")

    # 4. Add the full context (truncated if needed)
    if full_context:
        remaining = max_tokens - sum(len(p) for p in parts) - 100
        if remaining > 200:
            truncated = full_context[:remaining]
            parts.append(f"Additional context:\n{truncated}")

    if not parts:
        return goal

    return "\n\n".join(parts)


def _extract_triggering_request(messages: List[Dict], goal: str) -> str:
    """Find the user message that triggered this delegation."""
    # Look for the most recent user message that relates to the goal
    goal_words = set(goal.lower().split())
    goal_words -= {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
                   "for", "of", "with", "by", "from", "is", "it", "this", "that",
                   "please", "can", "you", "help", "me", "need", "want"}

    best_match = ""
    best_score = 0

    for msg in reversed(messages):
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role != "user" or not content:
            continue

        content_words = set(content.lower().split())
        overlap = goal_words & content_words
        score = len(overlap)

        if score > best_score:
            best_score = score
            best_match = content[:500]

    return best_match


def _extract_relevant_findings(messages: List[Dict], goal: str) -> str:
    """Extract tool results and assistant findings relevant to the goal."""
    goal_words = set(goal.lower().split())
    goal_words -= {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
                   "for", "of", "with", "by", "from", "is", "it", "this", "that"}

    findings = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content:
            continue

        # Check tool results
        if role == "tool":
            content_lower = content.lower()
            overlap = sum(1 for w in goal_words if w in content_lower)
            if overlap >= 2:
                findings.append(f"- Tool result: {content[:300]}")

        # Check assistant findings
        elif role == "assistant":
            content_lower = content.lower()
            overlap = sum(1 for w in goal_words if w in content_lower)
            if overlap >= 2 and len(content) > 50:
                findings.append(f"- Finding: {content[:300]}")

    if not findings:
        return ""

    # Take the most recent 5 relevant findings
    return "\n".join(findings[-5:])


def _extract_constraints(messages: List[Dict]) -> str:
    """Extract any constraints or requirements mentioned."""
    constraint_patterns = [
        r"(?:must|should|need to|have to|make sure)\s+(.{10,100})",
        r"(?:don't|do not|never|avoid)\s+(.{10,100})",
        r"(?:constraint|requirement|rule):\s*(.{10,100})",
    ]

    constraints = []
    for msg in messages:
        content = msg.get("content", "")
        if not content:
            continue
        for pattern in constraint_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                constraint = match.strip()
                if constraint and len(constraint) > 10:
                    constraints.append(f"- {constraint}")

    if not constraints:
        return ""

    return "\n".join(constraints[:5])


def build_handoff_messages(
    goal: str,
    context: str,
    system_prompt: str,
    conversation_messages: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Build the message list for a sub-agent with rewritten context.

    Returns a clean, focused message list that gives the sub-agent
    only what it needs to accomplish its goal.
    """
    rewritten = rewrite_context(goal, context, conversation_messages)

    return [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": (
                f"Goal: {goal}\n\n"
                f"Context:\n{rewritten}\n\n"
                "Complete this goal using the available tools. "
                "Be concise and focused."
            ),
        },
    ]
