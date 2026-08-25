"""Role-Based Agent Personas — role/goal/backstory contracts.

Pattern from CrewAI: each agent is defined by a role (what it does),
goal (what it optimizes for), and backstory (context shaping its behavior).
This goes beyond system prompts — the trio creates persistent behavioral bias.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nally.personas")


@dataclass
class AgentPersona:
    """A role-based agent persona with behavioral contract."""
    name: str
    role: str  # What this agent does
    goal: str  # What this agent optimizes for
    backstory: str  # Context shaping behavior and decision-making
    tools: List[str] = field(default_factory=list)  # Tools this persona can use
    expected_output: str = ""  # What the output should look like
    max_iterations: int = 10
    temperature: float = 0.7

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "goal": self.goal,
            "backstory": self.backstory[:200],
            "tools": self.tools,
            "expected_output": self.expected_output,
        }

    def to_system_prompt(self) -> str:
        """Generate a system prompt from this persona."""
        parts = [
            f"You are {self.name}.",
            f"Your role: {self.role}",
            f"Your goal: {self.goal}",
            f"Background: {self.backstory}",
        ]
        if self.expected_output:
            parts.append(f"\nExpected output format:\n{self.expected_output}")
        if self.tools:
            parts.append(f"\nAvailable tools: {', '.join(self.tools)}")
        return "\n".join(parts)


class PersonaRegistry:
    """Registry of available agent personas."""

    def __init__(self):
        self._personas: Dict[str, AgentPersona] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register default personas for common tasks."""
        self.register(AgentPersona(
            name="Research Analyst",
            role="Information gathering and analysis",
            goal="Accurate, well-sourced information with clear citations",
            backstory="Expert researcher with attention to detail. Values accuracy over speed. "
                      "Always cross-references multiple sources before stating facts.",
            tools=["web_search", "fetch", "read_file"],
            expected_output="Structured analysis with source citations and confidence levels.",
            temperature=0.3,
        ))

        self.register(AgentPersona(
            name="Code Engineer",
            role="Writing, debugging, and reviewing code",
            goal="Clean, efficient, well-tested code that follows best practices",
            backstory="Senior engineer who values code quality, maintainability, and testing. "
                      "Writes production-ready code, not prototypes. Reviews before shipping.",
            tools=["run_code", "code_analysis", "read_file", "file_ops", "run_command"],
            expected_output="Complete, tested code with error handling and documentation.",
            temperature=0.2,
        ))

        self.register(AgentPersona(
            name="Creative Writer",
            role="Writing, drafting, storytelling, and creative content",
            goal="Engaging, original content that matches the requested tone and style",
            backstory="Creative writer with a talent for voice matching. Adapts tone from "
                      "casual Lagos vibes to formal business writing as needed.",
            tools=["web_search", "fetch"],
            expected_output="Polished creative content in the requested style and format.",
            temperature=0.8,
        ))

        self.register(AgentPersona(
            name="Task Planner",
            goal="Breaking complex tasks into clear, executable steps",
            role="Planning and organizing multi-step work",
            backstory="Organized planner who thinks in sequences and dependencies. "
                      "Breaks complex goals into atomic, testable steps with clear success criteria.",
            tools=[],
            expected_output="Numbered step-by-step plan with dependencies and success criteria.",
            temperature=0.4,
        ))

        self.register(AgentPersona(
            name="Critical Reviewer",
            role="Reviewing work for quality, accuracy, and completeness",
            goal="Find issues, gaps, and improvements before the user sees the work",
            backstory="Strict quality reviewer who looks for problems others miss. "
                      "Evaluates accuracy, completeness, edge cases, and potential failures.",
            tools=[],
            expected_output="Structured review with severity ratings and specific improvement suggestions.",
            temperature=0.3,
        ))

    def register(self, persona: AgentPersona):
        """Register a persona."""
        self._personas[persona.name] = persona

    def get(self, name: str) -> Optional[AgentPersona]:
        """Get a persona by name."""
        return self._personas.get(name)

    def find_by_intent(self, task_description: str) -> Optional[AgentPersona]:
        """Find the best persona for a task."""
        desc_lower = task_description.lower()

        # Keyword matching
        persona_keywords = {
            "Research Analyst": ["research", "search", "find", "look up", "analyze", "compare", "investigate"],
            "Code Engineer": ["code", "program", "script", "function", "debug", "fix", "implement", "build"],
            "Creative Writer": ["write", "draft", "compose", "story", "blog", "content", "creative"],
            "Task Planner": ["plan", "organize", "break down", "steps", "roadmap", "schedule"],
            "Critical Reviewer": ["review", "check", "verify", "validate", "audit", "evaluate"],
        }

        best_match = None
        best_score = 0

        for persona_name, keywords in persona_keywords.items():
            score = sum(1 for kw in keywords if kw in desc_lower)
            if score > best_score:
                best_score = score
                best_match = persona_name

        if best_match and best_score >= 2:
            return self._personas.get(best_match)

        # Default: Research Analyst for unknown tasks
        return self._personas.get("Research Analyst")

    def list_all(self) -> List[Dict[str, Any]]:
        """List all registered personas."""
        return [p.to_dict() for p in self._personas.values()]


# Singleton
persona_registry = PersonaRegistry()
