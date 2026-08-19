"""Engineering build tool — the deterministic entry the `build` skill calls.

Registration here is the *only* change required to the existing tool registry
for the engineering subsystem to be reachable from the assistant. The tool
constructs a real :class:`EngineeringLoop` (Nally LLM backend + real, gated
toolbox + sandboxed workspace) and runs it, returning a short summary string
(including the output directory) to the agent.
"""

from __future__ import annotations

from typing import Dict

from .loop import EngineeringLoop
from .models import EngineeringError
from .protocol import NallyLLMBackend
from .toolbox import RealToolbox
from .workspace import EngineeringWorkspace


class EngineeringBuild:
    """Tool wrapper conforming to the Nally ``Tool`` interface."""

    name = "engineering_build"
    description = (
        "Autonomously design and implement a full software project from a high-level "
        "task. Runs the multi-stage engineering loop (intake -> brainstorm 3+ approaches "
        "-> score -> design -> test plan -> implement -> test -> self-critique -> refine "
        "-> README). Use only for explicit 'build/create a project/system/app' requests."
    )
    parameters = {
        "task": {
            "type": "string",
            "description": "The high-level task, e.g. 'Build a CLI tool that organizes files by extension'.",
            "required": True,
        }
    }
    permission = "destructive"

    def execute(self, task: str = "", **kwargs) -> str:
        if not task:
            return "Error: engineering_build requires a 'task' argument."

        try:
            backend = NallyLLMBackend()
            toolbox = RealToolbox(auto_approve_ask=True)
            workspace = EngineeringWorkspace(task=task)
            loop = EngineeringLoop(backend, toolbox, workspace)
            result = loop.run(task)
        except EngineeringError as exc:
            return f"Engineering build failed: {exc}"
        except Exception as exc:  # pragma: no cover - defensive
            return f"Engineering build error: {exc}"

        status = "SUCCESS" if result.success else "COMPLETED WITH ISSUES"
        lines = [
            f"[{status}] Engineering build for: {result.task}",
            f"Chosen approach: {result.chosen_approach.title if result.chosen_approach else 'n/a'}",
            f"Refinement passes: {result.refinements}",
            f"Artifacts: {', '.join(result.artifacts) or 'none'}",
            f"README: {result.readme_path}",
            f"Manifest: {result.manifest_path}",
            "Run commands:",
        ]
        lines.extend(f"  {c}" for c in result.run_commands)
        return "\n".join(lines)


def register() -> None:
    """Register the engineering build tool with the Nally tool registry."""
    try:
        from ..tools.registry import Tool, registry

        class _RegisteredTool(Tool):
            def __init__(self):
                super().__init__(
                    name=EngineeringBuild.name,
                    description=EngineeringBuild.description,
                    parameters=EngineeringBuild.parameters,
                    permission=EngineeringBuild.permission,
                )

            def execute(self, **kwargs):
                return EngineeringBuild().execute(**kwargs)

        registry.register(_RegisteredTool())
    except Exception as exc:  # pragma: no cover - registration guard
        # Registration is best-effort; the CLI path does not need the registry.
        import logging

        logging.getLogger("nally.engineering").warning(
            f"Could not register engineering_build tool: {exc}"
        )
