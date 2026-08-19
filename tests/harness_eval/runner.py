"""Harness Evaluation Runner — runs test cases and outputs pass/fail with metrics.

Usage:
    python -m tests.harness_eval.runner [--cases PATH] [--output PATH]

Reads test cases from JSON files, runs them through the harness classifier
(and optionally the full pipeline), and outputs structured results.
"""

import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


@dataclass
class EvalCase:
    """A single evaluation test case."""
    id: str
    input: str
    task_class: str
    expected_behavior: str
    pass_criteria: str


@dataclass
class EvalResult:
    """Result of running a single eval case."""
    case_id: str
    input_text: str
    expected_class: str
    actual_class: str
    class_match: bool
    pass_criteria_met: bool
    stages_fired: List[str]
    latency_ms: float
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_cases(cases_dir: Optional[str] = None) -> List[EvalCase]:
    """Load all test cases from JSON files in the cases directory."""
    if cases_dir is None:
        cases_dir = str(Path(__file__).parent / "cases")

    cases = []
    cases_path = Path(cases_dir)
    if not cases_path.exists():
        return cases

    for json_file in sorted(cases_path.glob("*.json")):
        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    cases.append(EvalCase(**item))
            elif isinstance(data, dict):
                cases.append(EvalCase(**data))
        except Exception as e:
            print(f"Warning: Failed to load {json_file}: {e}")

    return cases


def run_eval_case(case: EvalCase) -> EvalResult:
    """Run a single eval case through the harness classifier."""
    from nally.agent.harness import classify_intent, TaskClass

    start = time.time()

    try:
        classification = classify_intent(case.input)
        actual_class = classification.task_class.value
        class_match = actual_class == case.task_class

        # For pass criteria, we do a simple keyword check
        # (in production, this would be an LLM-as-judge call)
        pass_met = _check_pass_criteria(case, classification)

        latency = (time.time() - start) * 1000

        return EvalResult(
            case_id=case.id,
            input_text=case.input[:100],
            expected_class=case.task_class,
            actual_class=actual_class,
            class_match=class_match,
            pass_criteria_met=pass_met,
            stages_fired=["router"],
            latency_ms=latency,
        )
    except Exception as e:
        latency = (time.time() - start) * 1000
        return EvalResult(
            case_id=case.id,
            input_text=case.input[:100],
            expected_class=case.task_class,
            actual_class="ERROR",
            class_match=False,
            pass_criteria_met=False,
            stages_fired=[],
            latency_ms=latency,
            error=str(e),
        )


def _check_pass_criteria(case: EvalCase, classification) -> bool:
    """Check if pass criteria are met (heuristic, not LLM-based)."""
    criteria = case.pass_criteria.lower()

    # For injection cases, check that the classification is reasonable
    if "injection" in case.id:
        # Injection attempts should NOT be classified as HIGH_STAKES (which
        # would trigger extra caution) — they should be SIMPLE or AMBIGUOUS
        return classification.task_class.value in ("SIMPLE", "AMBIGUOUS", "KNOWLEDGE")

    # For tool_fail cases, any classification is fine
    if "tool_fail" in case.id:
        return True

    # For high_stakes, check it's classified as HIGH_STAKES
    if case.task_class == "HIGH_STAKES":
        return classification.task_class.value == "HIGH_STAKES"

    # For all other cases, class match is sufficient
    return classification.task_class.value == case.task_class


def run_all_evals(cases_dir: Optional[str] = None) -> Dict[str, Any]:
    """Run all eval cases and return summary results."""
    cases = load_cases(cases_dir)
    if not cases:
        return {"error": "No test cases found", "total": 0}

    results = []
    for case in cases:
        result = run_eval_case(case)
        results.append(result)

    total = len(results)
    passed = sum(1 for r in results if r.class_match and r.pass_criteria_met)
    class_matches = sum(1 for r in results if r.class_match)
    avg_latency = sum(r.latency_ms for r in results) / total if total > 0 else 0
    errors = sum(1 for r in results if r.error)

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": f"{(passed/total*100):.1f}%",
        "class_matches": class_matches,
        "class_accuracy": f"{(class_matches/total*100):.1f}%",
        "avg_latency_ms": round(avg_latency, 1),
        "errors": errors,
        "results": [r.to_dict() for r in results],
    }


def print_results(summary: Dict[str, Any]):
    """Print eval results in a readable format."""
    print(f"\n{'='*60}")
    print(f"  HARNESS EVALUATION RESULTS")
    print(f"{'='*60}")
    print(f"  Total cases:    {summary['total']}")
    print(f"  Passed:         {summary['passed']}")
    print(f"  Failed:         {summary['failed']}")
    print(f"  Pass rate:      {summary['pass_rate']}")
    print(f"  Class accuracy: {summary['class_accuracy']}")
    print(f"  Avg latency:    {summary['avg_latency_ms']}ms")
    print(f"  Errors:         {summary['errors']}")
    print(f"{'='*60}\n")

    for r in summary.get("results", []):
        status = "PASS" if r["class_match"] and r["pass_criteria_met"] else "FAIL"
        icon = "[+]" if status == "PASS" else "[-]"
        print(f"  {icon} {r['case_id']}: {r['expected_class']} -> {r['actual_class']} "
              f"({'match' if r['class_match'] else 'MISMATCH'}) [{r['latency_ms']:.0f}ms]")
        if r.get("error"):
            print(f"      ERROR: {r['error']}")
    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run harness evaluation")
    parser.add_argument("--cases", type=str, help="Path to cases directory")
    parser.add_argument("--output", type=str, help="Path to output JSON file")
    args = parser.parse_args()

    summary = run_all_evals(args.cases)
    print_results(summary)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"Results saved to {args.output}")
