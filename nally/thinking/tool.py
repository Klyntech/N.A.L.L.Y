from ..tools.registry import Tool
from .engine import thinking_engine


class ThinkTool(Tool):
    """Think tool — runs structured reasoning strategies on a question."""

    def __init__(self):
        super().__init__(
            name="think",
            description="Run structured thinking strategies on a question. Use for brainstorming, decision-making, analysis, and complex reasoning. Takes a question, optional domain (code/life/business/all), and optional strategy names. Returns multi-perspective analysis.",
            parameters={
                "question": {
                    "type": "string",
                    "description": "The question or problem to think about",
                    "required": True,
                },
                "domain": {
                    "type": "string",
                    "description": "Domain context: code, life, business, or all",
                    "required": False,
                },
                "strategies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific strategies to use (e.g. decision_matrix, pre_mortem, six_hats). If omitted, auto-selects based on question.",
                    "required": False,
                },
                "max_strategies": {
                    "type": "integer",
                    "description": "Maximum number of strategies to run",
                    "required": False,
                },
            },
            permission="safe",
        )

    def execute(self, **kwargs) -> str:
        question = kwargs.get("question", "")
        if not question:
            return "Error: 'question' parameter is required."

        domain = kwargs.get("domain", "all")
        strategies = kwargs.get("strategies")
        max_strategies = kwargs.get("max_strategies", 3)

        if strategies and isinstance(strategies, str):
            strategies = [s.strip() for s in strategies.split(",")]

        result = thinking_engine.think(
            question=question,
            domain=domain,
            strategies=strategies,
            max_strategies=max_strategies,
        )

        if not result.get("thinking_enabled"):
            return "Thinking is currently disabled."

        synthesis = result.get("synthesis", "")
        if not synthesis:
            return "I ran the analysis but couldn't produce a synthesis."

        # Format output
        lines = [f"THINKING ANALYSIS: {question}", ""]

        strategies_run = result.get("strategies_run", [])
        if strategies_run:
            lines.append(f"Strategies used: {', '.join(strategies_run)}")
            lines.append("")

        lines.append(synthesis)

        return "\n".join(lines)
