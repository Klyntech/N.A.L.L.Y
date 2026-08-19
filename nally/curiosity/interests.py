"""Interest Inference — extract user interests from behavioral signals.

Reads tool receipts (what the user asked about), memory episodes (what happened),
semantic patterns (what stuck), and user profile (declared interests).
Returns a list of interest keywords for the curiosity scanner to match against.
"""

import json
import re
from collections import Counter
from typing import Dict, List, Optional

# Stopwords to exclude from keyword extraction
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "this", "that", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "could", "should", "may", "might", "can",
    "shall", "not", "no", "if", "then", "else", "when", "up", "out",
    "so", "how", "what", "why", "which", "who", "whom", "where", "all",
    "each", "every", "both", "few", "more", "most", "other", "some",
    "such", "than", "too", "very", "just", "about", "also", "into",
    "over", "after", "before", "between", "under", "again", "there",
    "here", "once", "only", "own", "same", "its", "my", "your", "his",
    "her", "our", "their", "me", "him", "us", "them", "i", "you", "he",
    "she", "we", "they", "am", "as", "get", "got", "make", "made",
    "like", "just", "now", "still", "even", "way", "well", "back",
    "good", "new", "first", "last", "long", "great", "little", "right",
    "big", "high", "old", "different", "next", "small", "large", "part",
    "say", "said", "go", "going", "come", "came", "take", "took",
    "see", "saw", "know", "knew", "think", "thought", "use", "used",
    "find", "found", "want", "give", "gave", "tell", "told", "work",
    "run", "try", "keep", "let", "begin", "show", "help", "start",
    "need", "feel", "become", "leave", "put", "mean", "call", "done",
    "set", "file", "files", "code", "error", "fix", "debug", "test",
    "query", "string", "list", "data", "type", "function", "class",
    "module", "import", "return", "true", "false", "none", "null",
    "value", "key", "item", "element", "object", "result", "output",
    "input", "default", "user", "config", "option", "command", "run",
    "using", "use", "used", "check", "checked", "make", "made",
})

# Tool names that signal specific interests
_TOOL_INTEREST_MAP = {
    "web_search": "web_research",
    "fetch": "web_research",
    "run_code": "programming",
    "run_command": "system_admin",
    "read_file": "coding",
    "file_ops": "coding",
    "image_gen": "image_generation",
    "gmail_send": "email_communication",
    "gmail_read": "email_communication",
    "engineering_build": "software_engineering",
}


def infer_interests(
    receipts: List[Dict],
    episodes: List[Dict],
    semantic_patterns: List[Dict],
    profile_interests: Optional[str] = None,
    max_interests: int = 15,
) -> List[str]:
    """Infer user interests from behavioral signals.

    Args:
        receipts: Recent tool execution receipts (dicts with 'tool', 'args', 'result').
        episodes: Recent memory episodes (dicts with 'topic', 'what_happened', 'tags').
        semantic_patterns: Semantic memory patterns (dicts with 'pattern', 'confidence').
        profile_interests: User's declared interests from profile (JSON string or comma-separated).
        max_interests: Max interests to return.

    Returns:
        List of interest keywords, most relevant first.
    """
    counter: Counter = Counter()

    # 1. Declared interests (highest weight)
    for interest in _parse_profile_interests(profile_interests):
        counter[interest] += 3.0

    # 2. Tool usage patterns (medium weight)
    for receipt in receipts:
        tool = receipt.get("tool", "")
        interest = _TOOL_INTEREST_MAP.get(tool)
        if interest:
            counter[interest] += 1.5

        # Extract keywords from tool args
        args = receipt.get("args", {})
        if isinstance(args, dict):
            for val in args.values():
                if isinstance(val, str):
                    for kw in _extract_keywords(val):
                        counter[kw] += 0.5

    # 3. Episode topics and tags (high weight)
    for episode in episodes:
        topic = episode.get("topic", "")
        for kw in _extract_keywords(topic):
            counter[kw] += 2.0

        tags = episode.get("tags", "")
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except (json.JSONDecodeError, TypeError):
                tags = []
        if isinstance(tags, list):
            for tag in tags:
                counter[tag.lower()] += 2.5

        # Extract from what_happened
        what = episode.get("what_happened", "")
        for kw in _extract_keywords(what):
            counter[kw] += 0.5

    # 4. Semantic patterns (medium weight, confidence-scaled)
    for pattern in semantic_patterns:
        text = pattern.get("pattern", "")
        confidence = pattern.get("confidence", 0.5)
        for kw in _extract_keywords(text):
            counter[kw] += 1.0 * confidence

    # 5. Filter and sort
    # Remove stopwords and very short keywords
    filtered = {
        kw: score for kw, score in counter.items()
        if kw not in _STOPWORDS and len(kw) >= 3
    }

    # Sort by score, return top N
    sorted_interests = sorted(filtered.items(), key=lambda x: x[1], reverse=True)
    return [kw for kw, _ in sorted_interests[:max_interests]]


def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords from text."""
    if not text:
        return []
    # Lowercase, split on non-alphanumeric
    words = re.split(r'[^a-zA-Z0-9_]+', text.lower())
    return [w for w in words if w and w not in _STOPWORDS and len(w) >= 3]


def _parse_profile_interests(interests: Optional[str]) -> List[str]:
    """Parse declared interests from profile value."""
    if not interests:
        return []
    # Try JSON array first
    try:
        parsed = json.loads(interests)
        if isinstance(parsed, list):
            return [str(i).lower().strip() for i in parsed if i]
    except (json.JSONDecodeError, TypeError):
        pass
    # Fall back to comma-separated
    return [i.strip().lower() for i in interests.split(",") if i.strip()]
