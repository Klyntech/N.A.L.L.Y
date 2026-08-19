"""Engineering loop orchestrator.

A deterministic, stage-driven state machine that turns a raw task into a
production-quality project. It depends ONLY on:

* an :class:`LLMBackend` (real or fake) for all language-model calls, and
* a :class:`Toolbox` (real or fake) for all filesystem / shell access.

This decoupling is what makes the full loop drivable end-to-end by
``FakeLLMBackend`` + ``FakeToolbox`` with no API key and no real side effects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .intake import (
    is_ambiguous,
    parse_assumptions,
    parse_task,
)
from .approaches import ensure_categories, parse_approaches
from .models import (
    Approach,
    ApproachScore,
    CritiqueReport,
    DesignPlan,
    EngineeringError,
    EngineeringResult,
    EngineeringStage,
    TaskSpec,
    TestPlan,
)
from .plan import parse_design_plan, parse_implementation, parse_test_plan
from .prompts import (
    brainstorm_prompt,
    brainstorm_system,
    clarify_system,
    critique_prompt,
    critique_system,
    design_prompt,
    design_system,
    finalize_prompt,
    implement_prompt,
    implement_system,
    intake_prompt,
    test_plan_prompt,
    test_plan_system,
)
from .review import review_codebase, summarize_findings
from .scoring import score_approaches, select_best
from .workspace import EngineeringWorkspace


class EngineeringLoop:
    """Closed-loop autonomous engineering pipeline."""

    def __init__(
        self,
        backend: Any,
        toolbox: Any,
        workspace: EngineeringWorkspace,
        *,
        max_refinements: int = 3,
        emit: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        clarify_callback: Optional[Callable[[str], str]] = None,
        abort_fn: Optional[Callable[[], bool]] = None,
    ):
        self.backend = backend
        self.toolbox = toolbox
        self.workspace = workspace
        self.max_refinements = max_refinements
        self.emit = emit or (lambda stage, data: None)
        self.clarify_callback = clarify_callback
        self.abort_fn = abort_fn
        self._written: Dict[str, str] = {}

    # ── Public entry ────────────────────────────────────────

    def run(self, task: str) -> EngineeringResult:
        self.workspace.ensure()
        spec: Optional[TaskSpec] = None
        chosen: Optional[Approach] = None
        scores: List[ApproachScore] = []
        design: Optional[DesignPlan] = None
        test_plan: Optional[TestPlan] = None
        artifacts: List[str] = []
        refinements = 0
        test_ok = False
        report: Optional[CritiqueReport] = None

        try:
            self._check_abort()

            # 1. INTAKE
            spec = parse_task(task)
            self._stage(EngineeringStage.INTAKE, {"goal": spec.goal})

            # 2. CLARIFY / ASSUMPTIONS
            assumptions_text = self.backend.complete(
                clarify_system(), intake_prompt(task), stage="clarify", expect_json=True
            )
            spec.assumptions = parse_assumptions(assumptions_text)
            if is_ambiguous(spec) and self.clarify_callback:
                question = (
                    "I can build this autonomously. A few assumptions I'll make: "
                    + "; ".join(a.statement for a in spec.assumptions)
                    + ". Proceed? (or give constraints)"
                )
                answer = self.clarify_callback(question)
                if answer:
                    spec.assumptions = parse_assumptions(answer) or spec.assumptions
            self._stage(
                EngineeringStage.CLARIFY,
                {"assumptions": [a.statement for a in spec.assumptions]},
            )

            # 3. BRAINSTORM
            self._check_abort()
            raw = self.backend.complete(
                brainstorm_system(),
                brainstorm_prompt(spec),
                stage="brainstorm",
                expect_json=True,
            )
            approaches = ensure_categories(parse_approaches(raw))
            self._stage(EngineeringStage.BRAINSTORM, {"count": len(approaches)})

            # 4. SCORE
            scores = score_approaches(approaches)
            self._stage(
                EngineeringStage.SCORE,
                {"scores": [s.to_dict() for s in scores]},
            )

            # 5. SELECT
            chosen = select_best(scores, approaches)
            self._stage(EngineeringStage.SELECT, {"chosen_id": chosen.id})

            # 6. DESIGN
            self._check_abort()
            design_text = self.backend.complete(
                design_system(), design_prompt(spec, chosen), stage="design", expect_json=True
            )
            design = parse_design_plan(design_text, spec.goal)
            self._stage(
                EngineeringStage.DESIGN,
                {"files": [f.path for f in design.file_plan]},
            )

            # 7. TEST PLAN
            test_text = self.backend.complete(
                test_plan_system(),
                test_plan_prompt(spec, design),
                stage="test_plan",
                expect_json=True,
            )
            test_plan = parse_test_plan(test_text)
            self._stage(
                EngineeringStage.TESTPLAN,
                {"framework": test_plan.framework, "cases": len(test_plan.cases)},
            )

            # 8. IMPLEMENT (initial)
            self._check_abort()
            files = self._implement_with_retry(spec, design, test_plan, mode="initial", stage_label="implement")
            artifacts = self._write_files(files)
            self._stage(EngineeringStage.IMPLEMENT, {"files": list(files.keys())})

            # 9-11. TEST / CRITIQUE / REFINE loop
            for attempt in range(self.max_refinements + 1):
                self._check_abort()
                test_out, test_ok = self._run_tests(spec, design, test_plan)
                findings = review_codebase(self._written)
                report = summarize_findings(findings)
                self._stage(
                    EngineeringStage.CRITIQUE,
                    {
                        "passed": test_ok,
                        "needs_refinement": report.needs_refinement,
                        "high": report.high_count,
                        "medium": report.medium_count,
                    },
                )

                if test_ok and not report.needs_refinement:
                    break
                if attempt >= self.max_refinements:
                    break

                # REFINE
                self.backend.complete(
                    critique_system(),
                    critique_prompt(
                        spec, design, test_out, test_ok, self._fmt_findings(findings)
                    ),
                    stage="refine",
                    expect_json=True,
                )
                files = self._implement_with_retry(spec, design, test_plan, mode="refine", stage_label="refine")
                artifacts = self._write_files(files)
                refinements += 1
                self._stage(EngineeringStage.REFINE, {"iteration": refinements})

            # 12. FINALIZE
            result = self._finalize(
                spec, chosen, scores, design, test_plan, artifacts, refinements, test_ok, report
            )
            self._stage(EngineeringStage.FINALIZE, {"readme": result.readme_path})
            self._stage(EngineeringStage.DONE, {"success": result.success})
            return result

        except EngineeringError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise EngineeringError(f"Engineering loop failed: {exc}") from exc
        finally:
            self.workspace.save_manifest()

    # ── Internal helpers ────────────────────────────────────

    def _check_abort(self) -> None:
        if self.abort_fn and self.abort_fn():
            raise EngineeringError("Engineering loop aborted by request.")

    def _stage(self, stage: EngineeringStage, detail: Dict[str, Any]) -> None:
        self.workspace.record_stage(stage, detail)
        self.emit(stage.value, detail)

    def _implement(
        self, spec: TaskSpec, design: DesignPlan, test_plan: TestPlan, mode: str, stage_label: str
    ) -> Dict[str, str]:
        text = self.backend.complete(
            implement_system(),
            implement_prompt(spec, design, test_plan, mode=mode),
            stage=stage_label,
            expect_json=True,
        )
        return parse_implementation(text)

    def _implement_with_retry(
        self,
        spec: TaskSpec,
        design: DesignPlan,
        test_plan: TestPlan,
        mode: str,
        stage_label: str,
        attempts: int = 3,
    ) -> Dict[str, str]:
        """Call ``_implement`` with retry so a transient empty/parse failure
        (e.g. LLM returning empty under load) does not abort the whole run."""
        last_exc: Optional[EngineeringError] = None
        for attempt in range(1, attempts + 1):
            try:
                return self._implement(spec, design, test_plan, mode=mode, stage_label=stage_label)
            except EngineeringError as exc:
                last_exc = exc
                if attempt < attempts:
                    self.emit(f"{stage_label}_retry", {"attempt": attempt, "error": str(exc)})
                    continue
        raise last_exc

    def _write_files(self, files: Dict[str, str]) -> List[str]:
        artifacts: List[str] = []
        for rel, content in files.items():
            abs_path = str(self.workspace.path_for(rel))
            self.toolbox.write_file(abs_path, content)
            self._written[rel] = content
            artifacts.append(rel)
        return artifacts

    def _run_tests(
        self, spec: TaskSpec, design: DesignPlan, test_plan: TestPlan
    ) -> Tuple[str, bool]:
        lang = (spec.language_hint or "python").lower()
        if lang == "python":
            return self.toolbox.run_tests("")
        cmd = self._test_command_for(lang, test_plan.framework)
        return self.toolbox.run_command(cmd)

    @staticmethod
    def _test_command_for(lang: str, framework: str) -> str:
        mapping = {
            "javascript": "npm test",
            "typescript": "npm test",
            "node": "npm test",
            "go": "go test ./...",
            "rust": "cargo test",
            "java": "mvn test",
            "ruby": "rspec",
            "php": "phpunit",
        }
        return mapping.get(lang, f"# no test command for {lang}")

    @staticmethod
    def _fmt_findings(findings) -> str:
        if not findings:
            return "none"
        return "\n".join(f"- [{f.severity.value}] {f.category.value}: {f.message}" for f in findings)

    def _finalize(
        self,
        spec: TaskSpec,
        chosen: Optional[Approach],
        scores: List[ApproachScore],
        design: Optional[DesignPlan],
        test_plan: Optional[TestPlan],
        artifacts: List[str],
        refinements: int,
        test_ok: bool,
        report: Optional[CritiqueReport],
    ) -> EngineeringResult:
        limitations = self._gather_limitations(spec, design, report)

        readme = self._build_readme(spec, chosen, scores, design, test_plan, artifacts, refinements, test_ok, limitations)
        readme_path = self.workspace.write_artifact("README.md", readme)

        scorecard_path = self.workspace.write_artifact(
            "scorecard.json", json.dumps([s.to_dict() for s in scores], indent=2)
        )

        deps = list(design.dependencies) if design else []
        if deps:
            self.workspace.write_artifact("requirements.txt", "\n".join(deps) + "\n")

        run_commands = self._run_commands(spec, design, deps)

        success = test_ok and (report is None or not report.needs_refinement)

        return EngineeringResult(
            task=spec.goal,
            chosen_approach=chosen,
            scorecard=scores,
            design=design,
            test_plan=test_plan,
            artifacts=artifacts,
            readme_path=str(readme_path),
            manifest_path=str(self.workspace.manifest_path),
            scorecard_path=str(scorecard_path),
            dependencies=deps,
            run_commands=run_commands,
            known_limitations=limitations,
            refinements=refinements,
            success=success,
            notes=(
                ["Tests passed and static review clean."]
                if success
                else ["Review flagged issues or tests failed; see artifacts."]
            ),
        )

    def _gather_limitations(
        self, spec: TaskSpec, design: Optional[DesignPlan], report: Optional[CritiqueReport]
    ) -> List[str]:
        limitations: List[str] = []
        # LLM-supplied limitations (best effort).
        try:
            text = self.backend.complete(
                "You list known limitations concisely.",
                finalize_prompt(spec, design, "see artifacts"),
                stage="finalize",
                expect_json=True,
            )
            data = json.loads(_safe_json(text))
            if isinstance(data, dict):
                limitations.extend(str(x) for x in data.get("known_limitations", []))
        except Exception:
            pass
        # Derived from static findings.
        if report:
            for f in report.findings:
                if f.severity.value in ("high", "medium"):
                    limitations.append(f"{f.category.value}: {f.message}")
        # Defaults if nothing else.
        if not limitations:
            limitations = [
                "Generated autonomously; not manually reviewed by a human.",
                "Test coverage is limited to the planned cases.",
                "Edge cases beyond the test plan may remain.",
            ]
        return limitations[:8]

    def _run_commands(
        self, spec: TaskSpec, design: Optional[DesignPlan], deps: List[str]
    ) -> List[str]:
        lang = (spec.language_hint or "python").lower()
        entry = (design.file_plan[0].path if design and design.file_plan else "main.py")
        if lang == "python":
            cmds = []
            if deps:
                cmds.append("python -m pip install -r requirements.txt")
            cmds.append("python -m pytest")
            cmds.append(f"python {entry}")
            return cmds
        if lang in ("javascript", "typescript", "node"):
            return ["npm install", "npm test", f"node {entry}"]
        if lang == "go":
            return ["go test ./...", f"go run {entry}"]
        if lang == "rust":
            return ["cargo test", "cargo run"]
        return [f"# run instructions for {lang}: see README"]

    def _build_readme(
        self,
        spec: TaskSpec,
        chosen: Optional[Approach],
        scores: List[ApproachScore],
        design: Optional[DesignPlan],
        test_plan: Optional[TestPlan],
        artifacts: List[str],
        refinements: int,
        test_ok: bool,
        limitations: List[str],
    ) -> str:
        lines: List[str] = []
        lines.append(f"# {spec.goal}")
        lines.append("")
        lines.append("> Generated autonomously by the Nally engineering loop.")
        lines.append("")
        lines.append("## Overview")
        lines.append("")
        lines.append(f"Goal: {spec.goal}")
        if spec.constraints:
            lines.append("")
            lines.append("Constraints:")
            for c in spec.constraints:
                lines.append(f"- {c}")
        if spec.assumptions:
            lines.append("")
            lines.append("Assumptions:")
            for a in spec.assumptions:
                lines.append(f"- {a.statement}")
        lines.append("")
        lines.append("## Chosen Approach")
        lines.append("")
        if chosen:
            lines.append(f"**{chosen.title}** ({chosen.category.value})")
            lines.append("")
            lines.append(chosen.summary)
            if chosen.pros:
                lines.append("")
                lines.append("Pros:")
                for p in chosen.pros:
                    lines.append(f"- {p}")
            if chosen.cons:
                lines.append("")
                lines.append("Cons:")
                for c in chosen.cons:
                    lines.append(f"- {c}")
        lines.append("")
        lines.append("## Scorecard")
        lines.append("")
        lines.append("| Approach | Feasibility | Simplicity | Maintainability | Performance | Novelty | Weighted |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        by_id = {s.approach_id: s for s in scores}
        if chosen and chosen.id in by_id:
            s = by_id[chosen.id]
            lines.append(
                f"| **{chosen.title}** | {s.feasibility} | {s.simplicity} | "
                f"{s.maintainability} | {s.performance} | {s.novelty} | {s.weighted_total:.2f} |"
            )
        lines.append("")
        lines.append("## Architecture")
        lines.append("")
        if design:
            lines.append(design.architecture_summary or "_See file plan below._")
            if design.components:
                lines.append("")
                lines.append("Components:")
                for c in design.components:
                    name = c.get("name", "component") if isinstance(c, dict) else str(c)
                    resp = c.get("responsibility", "") if isinstance(c, dict) else ""
                    lines.append(f"- **{name}**: {resp}")
            lines.append("")
            lines.append("### Files")
            for f in design.file_plan:
                lines.append(f"- `{f.path}` — {f.purpose}")
        lines.append("")
        lines.append("## Testing")
        lines.append("")
        if test_plan:
            lines.append(f"Framework: {test_plan.framework}")
            if test_plan.cases:
                lines.append("")
                lines.append("Cases:")
                for c in test_plan.cases:
                    lines.append(f"- {c.name}: {c.description}")
        lines.append("")
        lines.append(f"Tests passed: {'yes' if test_ok else 'no'} | Refinement passes: {refinements}")
        lines.append("")
        lines.append("## Dependencies")
        lines.append("")
        if self._deps(design):
            for d in self._deps(design):
                lines.append(f"- {d}")
            if (spec.language_hint or "python").lower() == "python":
                lines.append("")
                lines.append("Install with: `python -m pip install -r requirements.txt`")
        else:
            lines.append("No external dependencies.")
        lines.append("")
        lines.append("## Run Commands")
        lines.append("")
        for cmd in self._run_commands(spec, design, self._deps(design)):
            lines.append(f"- `{cmd}`")
        lines.append("")
        lines.append("## Known Limitations")
        lines.append("")
        for lim in limitations:
            lines.append(f"- {lim}")
        lines.append("")
        lines.append("## Artifacts")
        lines.append("")
        for a in artifacts:
            lines.append(f"- `{a}`")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _deps(design: Optional[DesignPlan]) -> List[str]:
        return list(design.dependencies) if design else []


def _safe_json(text: str) -> str:
    """Best-effort JSON extraction for the optional finalize step."""
    from ._json import extract_json

    try:
        return json.dumps(extract_json(text))
    except Exception:
        return "{}"
