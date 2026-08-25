"""SOUL.md — Hot-Reloadable Personality System.

Pattern from OpenClaw: personality defined in a standalone SOUL.md file
that can be hot-reloaded without restarting the agent. Enables rapid
iteration on personality without code changes.

SOUL.md format:
    # Soul
    ## Identity
    ## Tone Rules
    ## Reasoning Rules
    ## How You Work
    ## Examples
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("nally.soul")

# Default SOUL.md location
DEFAULT_SOUL_PATH = Path(__file__).parent.parent.parent / "SOUL.md"
FALLBACK_PERSONALITY = "nally"


class SoulManager:
    """Manages hot-reloadable personality from SOUL.md file."""

    def __init__(self, soul_path: Optional[str] = None):
        self._soul_path = Path(soul_path) if soul_path else DEFAULT_SOUL_PATH
        self._current_soul: Optional[str] = None
        self._last_hash: Optional[str] = None
        self._last_load_time: float = 0
        self._reload_interval: float = 30  # Check every 30 seconds

    def get_soul(self, force_reload: bool = False) -> str:
        """Get the current soul/personality text.

        Checks file modification time and reloads if changed.
        """
        now = time.time()

        # Check if we need to reload
        if not force_reload and self._current_soul:
            if now - self._last_load_time < self._reload_interval:
                return self._current_soul
            if not self._file_changed():
                return self._current_soul

        # Load from file
        soul = self._load_from_file()
        if soul:
            self._current_soul = soul
            self._last_load_time = now
            self._last_hash = self._compute_hash(soul)
            logger.info(f"SOUL.md loaded from {self._soul_path}")
            return soul

        # Fallback to config personality
        return self._load_fallback()

    def _load_from_file(self) -> Optional[str]:
        """Load SOUL.md from file."""
        try:
            if self._soul_path.exists():
                content = self._soul_path.read_text(encoding="utf-8")
                if content.strip():
                    return content
        except Exception as e:
            logger.warning(f"Failed to load SOUL.md: {e}")
        return None

    def _load_fallback(self) -> str:
        """Load fallback personality from config."""
        try:
            from ..config import get_system_prompt
            return get_system_prompt()
        except Exception:
            return "You are Nally, a helpful AI assistant."

    def _file_changed(self) -> bool:
        """Check if SOUL.md has been modified since last load."""
        try:
            if not self._soul_path.exists():
                return False
            current_hash = self._compute_hash(self._soul_path.read_text(encoding="utf-8"))
            return current_hash != self._last_hash
        except Exception:
            return False

    def _compute_hash(self, content: str) -> str:
        """Compute hash of content for change detection."""
        return hashlib.md5(content.encode()).hexdigest()

    def get_soul_sections(self) -> Dict[str, str]:
        """Parse SOUL.md into sections."""
        soul = self.get_soul()
        sections = {}
        current_section = None
        current_content = []

        for line in soul.split("\n"):
            if line.startswith("## "):
                if current_section:
                    sections[current_section] = "\n".join(current_content).strip()
                current_section = line[3:].strip()
                current_content = []
            else:
                current_content.append(line)

        if current_section:
            sections[current_section] = "\n".join(current_content).strip()

        return sections

    def get_identity(self) -> str:
        """Get the Identity section from SOUL.md."""
        sections = self.get_soul_sections()
        return sections.get("Identity", "You are Nally.")

    def get_tone_rules(self) -> str:
        """Get the Tone Rules section from SOUL.md."""
        sections = self.get_soul_sections()
        return sections.get("Tone Rules", "Be direct and helpful.")

    def get_reasoning_rules(self) -> str:
        """Get the Reasoning Rules section from SOUL.md."""
        sections = self.get_soul_sections()
        return sections.get("Reasoning Rules", "Think step by step.")

    def get_examples(self) -> str:
        """Get the Examples section from SOUL.md."""
        sections = self.get_soul_sections()
        return sections.get("Examples", "")

    def get_metadata(self) -> Dict[str, Any]:
        """Get metadata about the current soul."""
        return {
            "path": str(self._soul_path),
            "exists": self._soul_path.exists(),
            "last_load_time": self._last_load_time,
            "reload_interval": self._reload_interval,
            "hash": self._last_hash,
            "sections": list(self.get_soul_sections().keys()),
        }

    def watch(self, callback=None):
        """Start watching SOUL.md for changes.

        In production, this would use inotify/watchdog.
        For now, it checks on each get_soul() call.
        """
        logger.info(f"Watching {self._soul_path} for changes (interval: {self._reload_interval}s)")
        self._reload_interval = 5  # Faster reload when watching

    def create_default_soul(self):
        """Create a default SOUL.md file if it doesn't exist."""
        if self._soul_path.exists():
            return

        default_soul = """# Soul

## Identity
You are NALLY — Clinton's personal AI assistant, built in Lagos, Nigeria.
You are not a chatbot. You are a reasoning engine that thinks hard and gives straight answers.

## Tone Rules
- Be direct. Say what's wrong, what's right, and what to do instead.
- No fluff. No "Great question!" "Certainly!" "Absolutely!"
- Match the user's energy. Short text gets short reply.
- Say "idk" / "tbh" / "ngl" when it fits.
- Use contractions: I'll, you're, it's, don't, can't, won't.

## Reasoning Rules
- Before answering, think about what's actually being asked.
- For anything non-trivial: think step by step silently, then give the answer.
- When something breaks: identify the root cause first.
- Only respond to what the user ACTUALLY said.

## How You Work
1. UNDERSTAND FIRST — Read existing code before modifying anything.
2. PLAN BEFORE CODE — For complex tasks: write the plan first.
3. ONE TASK AT A TIME — Don't bundle unrelated changes.
4. VERIFY YOUR WORK — Run tests after writing code.
5. ASK WHEN UNSURE — If a task is ambiguous, ask.

## Examples
User: hey nally
You: Hey, what we doing today

User: can you help me write a python script
You: Yeah, what do you need

User: I got an error in my code
You: Send it, let me see
"""

        try:
            self._soul_path.parent.mkdir(parents=True, exist_ok=True)
            self._soul_path.write_text(default_soul, encoding="utf-8")
            logger.info(f"Created default SOUL.md at {self._soul_path}")
        except Exception as e:
            logger.warning(f"Failed to create SOUL.md: {e}")


# Singleton
soul_manager = SoulManager()
