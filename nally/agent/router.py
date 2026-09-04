"""Nally Router - Pattern Matching for Instant Responses.

Minimal allowlist of cheap, true, no-LLM-needed handlers (time/date/day/greet).
Everything else goes to the LLM for one brain, one voice.

Heavy / historical handlers (PC control, volume, brightness, files, weather,
eval, jokes, etc.) were intentionally removed. They belong behind Bridge /
permission gates, not regex.
"""

from datetime import datetime
from typing import Callable, List, Optional
import re


class Pattern:
    """Represents a pattern with handler and specificity."""

    def __init__(self, pattern: str, handler: Callable, specificity: int = 1):
        self.pattern = pattern
        self.handler = handler
        self.specificity = specificity
        self.compiled = re.compile(pattern, re.IGNORECASE)

    def match(self, text: str) -> Optional[re.Match]:
        return self.compiled.search(text)


class PatternMatcher:
    """Matches user input against patterns, returning most specific match."""

    def __init__(self):
        self.patterns: List[Pattern] = []

    def add(self, pattern: str, handler: Callable, specificity: int = 1):
        self.patterns.append(Pattern(pattern, handler, specificity))

    def match(self, user_input: str) -> Optional[Callable]:
        """Find most specific matching pattern. Returns a zero-arg callable."""
        best_match = None
        best_specificity = -1
        for pattern in self.patterns:
            m = pattern.match(user_input)
            if m and pattern.specificity > best_specificity:
                best_specificity = pattern.specificity
                best_match = lambda m=m, h=pattern.handler: h(m)
        return best_match


# ── Live handlers (only those registered below) ──────────────────────────────


def handle_time(match):
    now = datetime.now()
    return f"The current time is {now.strftime('%I:%M %p')}."


def handle_date(match):
    now = datetime.now()
    return f"Today is {now.strftime('%A, %B %d, %Y')}."


def handle_day(match):
    now = datetime.now()
    return f"It's {now.strftime('%A')}."


def handle_greet(match):
    return "Hey! How can I help you?"


def create_matcher() -> PatternMatcher:
    """Create and configure the pattern matcher — minimal allowlist."""
    m = PatternMatcher()
    m.add(r"what time is it|current time|what's the time|what time\b", handle_time, 10)
    m.add(r"what(?:'s| is) (?:the )?date|today's date|what day is it", handle_date, 10)
    m.add(r"what day\b|day of week", handle_day, 10)
    m.add(r"^hello$|^hi$|^hey$|^howdy$", handle_greet, 5)
    return m


# Singleton matcher
matcher = create_matcher()
