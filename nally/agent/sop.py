"""SOP-as-Runtime — typed Pydantic contracts for recurring workflows.

Pattern from MetaGPT: recurring personal workflows are encoded as formal
SOPs with typed contracts at each step. The procedure, not the persona,
is the source of truth.

Each SOP defines:
    - Input schema (Pydantic model)
    - Steps with typed output contracts
    - Output schema (Pydantic model)
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

logger = logging.getLogger("nally.sop")

try:
    from pydantic import BaseModel
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    BaseModel = None


@dataclass
class SOPStep:
    """A single step in an SOP with typed input/output."""
    name: str
    description: str
    tool: str = ""  # Tool to use for this step
    input_fields: List[str] = field(default_factory=list)
    output_fields: List[str] = field(default_factory=list)
    timeout: int = 30
    required: bool = True
    retry_on_failure: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tool": self.tool,
            "input_fields": self.input_fields,
            "output_fields": self.output_fields,
            "timeout": self.timeout,
            "required": self.required,
        }


@dataclass
class SOPDefinition:
    """A Standard Operating Procedure with typed contracts."""
    name: str
    description: str
    steps: List[SOPStep]
    input_schema: Optional[Dict[str, str]] = None  # field_name -> type description
    output_schema: Optional[Dict[str, str]] = None
    trigger_patterns: List[str] = field(default_factory=list)  # Regex patterns that trigger this SOP

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "trigger_patterns": self.trigger_patterns,
        }


@dataclass
class SOPResult:
    """Result of executing an SOP."""
    sop_name: str
    success: bool
    step_results: Dict[str, Any] = field(default_factory=dict)
    output: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)
    total_duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sop_name": self.sop_name,
            "success": self.success,
            "step_results": self.step_results,
            "output": self.output,
            "errors": self.errors,
            "total_duration_ms": self.total_duration_ms,
        }


class SOPEngine:
    """Registry and executor for SOPs."""

    def __init__(self):
        self._sops: Dict[str, SOPDefinition] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register common personal SOPs."""
        self.register(SOPDefinition(
            name="daily_briefing",
            description="Morning briefing: calendar, news, tasks",
            steps=[
                SOPStep(name="fetch_calendar", description="Get today's calendar events", tool="web_search"),
                SOPStep(name="fetch_news", description="Get top news headlines", tool="web_search"),
                SOPStep(name="fetch_tasks", description="Get pending tasks from memory", tool="recall"),
                SOPStep(name="summarize", description="Combine into briefing", tool=""),
            ],
            input_schema={"date": "string (YYYY-MM-DD)"},
            output_schema={"calendar": "list", "news": "list", "tasks": "list", "summary": "string"},
            trigger_patterns=[r"daily briefing", r"morning briefing", r"what's on today"],
        ))

        self.register(SOPDefinition(
            name="email_draft",
            description="Draft an email with proper structure",
            steps=[
                SOPStep(name="understand_intent", description="Parse recipient, subject, key points", tool=""),
                SOPStep(name="draft_email", description="Write the email body", tool=""),
                SOPStep(name="review", description="Check for tone, grammar, completeness", tool=""),
            ],
            input_schema={"recipient": "string", "subject": "string", "key_points": "list"},
            output_schema={"subject": "string", "body": "string", "tone": "string"},
            trigger_patterns=[r"draft.*email", r"compose.*email", r"write.*email"],
        ))

        self.register(SOPDefinition(
            name="expense_report",
            description="Generate expense report from receipts",
            steps=[
                SOPStep(name="gather_receipts", description="Find and parse receipts", tool="read_file"),
                SOPStep(name="categorize", description="Categorize expenses", tool=""),
                SOPStep(name="summarize", description="Create summary with totals", tool=""),
                SOPStep(name="export", description="Format as report", tool=""),
            ],
            input_schema={"date_range": "string", "receipt_files": "list"},
            output_schema={"categories": "dict", "total": "float", "report": "string"},
            trigger_patterns=[r"expense report", r"receipt.*summary", r"spending.*report"],
        ))

    def register(self, sop: SOPDefinition):
        """Register an SOP."""
        self._sops[sop.name] = sop

    def get(self, name: str) -> Optional[SOPDefinition]:
        """Get an SOP by name."""
        return self._sops.get(name)

    def find_by_intent(self, text: str) -> Optional[SOPDefinition]:
        """Find an SOP that matches the user's intent."""
        text_lower = text.lower()
        for sop in self._sops.values():
            for pattern in sop.trigger_patterns:
                import re
                if re.search(pattern, text_lower):
                    return sop
        return None

    def list_all(self) -> List[Dict[str, Any]]:
        """List all registered SOPs."""
        return [sop.to_dict() for sop in self._sops.values()]

    def validate_input(self, sop: SOPDefinition, data: Dict[str, Any]) -> List[str]:
        """Validate input data against SOP's input schema. Returns list of errors."""
        if not sop.input_schema:
            return []
        errors = []
        for field_name, field_type in sop.input_schema.items():
            if field_name not in data:
                errors.append(f"Missing required input: {field_name} ({field_type})")
        return errors

    def build_step_prompt(self, sop: SOPDefinition, step: SOPStep, context: Dict[str, Any]) -> str:
        """Build a prompt for executing a single SOP step."""
        parts = [
            f"You are executing step '{step.name}' of the '{sop.name}' SOP.",
            f"Goal: {step.description}",
        ]
        if context:
            parts.append(f"\nContext from previous steps:")
            for k, v in context.items():
                parts.append(f"  {k}: {str(v)[:200]}")
        if step.output_fields:
            parts.append(f"\nExpected output fields: {', '.join(step.output_fields)}")
        parts.append("\nExecute this step and return the result as JSON.")
        return "\n".join(parts)


# Singleton
sop_engine = SOPEngine()
