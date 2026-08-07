"""Skill registry — manages skill state, hot-swap, and activation."""

import logging
from pathlib import Path
from typing import Optional

from .loader import SKILLS_DIR, Skill, get_skill_manifest, load_skills

logger = logging.getLogger("nally.skills")


class SkillRegistry:
    """Singleton skill registry with hot-swap support."""

    def __init__(self):
        self._skills: dict[str, Skill] = {}
        self._loaded = False
        self._manifest = ""

    def load(self, skills_dir: Optional[Path] = None):
        """Load all skills (Level 1 + Level 2). Called at startup."""
        self._skills = load_skills(skills_dir)
        self._manifest = get_skill_manifest(skills_dir)
        self._loaded = True
        logger.info(f"Skill registry: {len(self._skills)} skills loaded")

    def reload(self, skills_dir: Optional[Path] = None):
        """Hot-swap: rescan skills directory without restart."""
        old_count = len(self._skills)
        self._skills = load_skills(skills_dir)
        self._manifest = get_skill_manifest(skills_dir)
        new_count = len(self._skills)
        logger.info(f"Skill registry reloaded: {old_count} -> {new_count} skills")

    @property
    def manifest(self) -> str:
        """Level 1: skill names + descriptions for system prompt."""
        return self._manifest

    @property
    def names(self) -> list[str]:
        return list(self._skills.keys())

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def activate(self, name: str) -> Optional[str]:
        """Level 2: return full skill body for triggered skill."""
        skill = self._skills.get(name)
        if not skill:
            return None
        return skill.body

    def find_by_intent(self, message: str) -> list[str]:
        """Find skills whose description matches the user's message intent.

        Returns list of matching skill names, ordered by relevance.
        """
        message_lower = message.lower()
        matches = []

        for name, skill in self._skills.items():
            desc_lower = skill.description.lower()
            # Simple keyword matching — description words in message
            desc_words = set(desc_lower.split())
            msg_words = set(message_lower.split())
            overlap = desc_words & msg_words
            # Require 3+ word overlap, OR full skill name in message (not partial segments)
            name_words = name.split("-")
            full_name_in_msg = len(name_words) >= 2 and all(
                kw in message_lower for kw in name_words
            )
            if len(overlap) >= 3 or full_name_in_msg:
                matches.append((name, len(overlap)))

        # Sort by relevance (most overlap first)
        matches.sort(key=lambda x: x[1], reverse=True)
        return [m[0] for m in matches]

    def create_skill(self, name: str, description: str, body: str, skills_dir: Optional[Path] = None) -> bool:
        """Create a new skill from a successful workflow (self-creation)."""
        skills_dir = skills_dir or SKILLS_DIR
        skill_dir = skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_md = skill_dir / "SKILL.md"
        content = f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"
        skill_md.write_text(content, encoding="utf-8")

        # Hot-swap reload
        self.reload(skills_dir)
        logger.info(f"Created skill: {name}")
        return True


# Singleton
skill_registry = SkillRegistry()
