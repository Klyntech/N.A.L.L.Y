"""Benchmark Runner — orchestrates the full NALLY benchmark.

Usage:
    python -m tests.benchmark.runner                        # Run all tasks, current model
    python -m tests.benchmark.runner --models opencode groq # Side-by-side comparison
    python -m tests.benchmark.runner --tasks tool_selection # Only specific category
    python -m tests.benchmark.runner --output results/      # Custom output dir
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Dict, List, Optional

# Ensure project root is on sys.path
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from .cases import ALL_TASKS, Task, TaskCategory, get_tasks_by_category
from .cost import CostTracker
from .judges import JudgeResult, run_judge
from .reporter import (
    generate_json_report,
    generate_markdown_report,
    write_json_report,
    write_markdown_report,
)


class BenchmarkSuite:
    """Runs NALLY through a curated task suite and measures performance."""

    def __init__(
        self,
        models: Optional[List[str]] = None,
        categories: Optional[List[TaskCategory]] = None,
        output_dir: str = "tests/benchmark/results",
        verbose: bool = True,
        mode: str = "nally",  # nally | raw | both (paired lift)
    ):
        self.models = models or [self._detect_current_model()]
        self.categories = categories or list(TaskCategory)
        self.output_dir = output_dir
        self.verbose = verbose
        self.mode = mode  # for NALLY Lift = NALLY - Raw
        self.cost_tracker = CostTracker()
        self._initialized = False

    @staticmethod
    def _detect_current_model() -> str:
        try:
            from nally.config import PROVIDER, ACTIVE_MODEL
            return f"{PROVIDER}/{ACTIVE_MODEL}"
        except Exception:
            return "unknown"

    def _log(self, msg: str):
        if self.verbose:
            print(f"  {msg}")

    def _ensure_initialized(self):
        """Load tools and override permissions for benchmark mode (run once)."""
        if self._initialized:
            return
        self._initialized = True

        # Load all tools into the registry
        try:
            from nally.tools import load_all_tools
            load_all_tools()
            self._log("[init] Tools loaded")
        except Exception as e:
            self._log(f"[init] Tool loading failed: {e}")

        # Override permission gate — keep denys for adversarial, allow-all for others
        try:
            from nally.tools.permissions import gate
            import json as _json
            # If adversarial tasks are in suite, use benchmark-specific permissions that keep denys
            has_adv = any(c == TaskCategory.ADVERSARIAL for c in self.categories)
            if has_adv:
                bench_perm = _project_root + "/tests/benchmark/permissions_benchmark.json"
                if os.path.exists(bench_perm):
                    gate._config = _json.loads(Path(bench_perm).read_text(encoding="utf-8"))
                    self._log("[init] Permissions: benchmark file (keeps adversarial denys)")
                else:
                    gate._config = {"*": "allow"}
                    self._log("[init] Permissions overridden to allow-all (no bench file)")
            else:
                gate._config = {"*": "allow"}
                self._log("[init] Permissions overridden to allow-all for benchmark")
        except Exception as e:
            self._log(f"[init] Permission override failed: {e}")

        # Raise token budget so the full 800-task benchmark can run (30M = ~1150 tasks at 26k avg)
        try:
            import nally.config as _cfg
            _cfg.DAILY_TOKEN_BUDGET = 30_000_000
            import nally.agent.context as _ctx
            _ctx.DAILY_TOKEN_BUDGET = 30_000_000
            from nally.agent.context import context_manager
            context_manager._daily_tokens = 0
            self._log("[init] Token budget raised to 30M for benchmark")
        except Exception as e:
            self._log(f"[init] Budget override failed: {e}")

    def _get_tasks(self) -> List[Task]:
        tasks = []
        for cat in self.categories:
            tasks.extend(get_tasks_by_category(cat))
        return tasks

    def _create_agent(self, model_override: Optional[str] = None):
        """Create a fresh NallyAgent for a single task."""
        self._ensure_initialized()

        session_id = f"bench_{uuid.uuid4().hex[:12]}"
        try:
            from nally.agent.core import NallyAgent
            agent = NallyAgent(session_id=session_id)

            # Swap model if doing comparison
            if model_override:
                agent._model_override = model_override

            return agent
        except Exception as e:
            print(f"  [WARN] Failed to create agent: {e}")
            return None

    def _clear_receipts(self):
        """Clear the in-memory receipt store for task isolation."""
        try:
            from nally.tools.receipts import receipt_store
            with receipt_store._lock:
                receipt_store._by_tool_call_id.clear()
        except Exception:
            pass

    def _run_raw(self, task: Task, model: str) -> Dict:
        """Run task directly against raw LLM (no tools, no memory, no graph) for NALLY Lift."""
        self._log(f"[{task.id}] RAW: {task.input[:60]}...")
        start_time = time.time()
        response = ""
        error = None
        try:
            from nally.agent.llm import llm
            # Minimal system prompt — same for all tasks, no NALLY persona
            response = llm.simple_chat(task.input, system_prompt="You are a helpful assistant. Be concise and accurate.")
        except Exception as e:
            error = str(e)
            response = f"Error: {e}"
            traceback.print_exc()
        elapsed_ms = (time.time() - start_time) * 1000

        # Raw has no receipts, no verification — judge via text validation only
        from .judges import run_judge as _run_judge
        # For raw, tool-based judges return N/A or 0 — we still run them for paired lift but report bucket separately
        try:
            judge_result = _run_judge(task, [], response, verification_result=None)
            # For tool-dependent categories, raw should be N/A not 0 for aggregate — but keep raw 0 for lift math
            # We keep as-is; reporter will bucket separately
        except Exception as e:
            from .judges import JudgeResult
            judge_result = JudgeResult(score=0.0, details=f"Raw judge error: {e}", passed=False)

        result = {
            "task_id": task.id,
            "category": task.category.value,
            "difficulty": task.difficulty,
            "input": task.input,
            "response": response[:2000],
            "score": judge_result.score,
            "passed": judge_result.passed,
            "details": f"RAW: {judge_result.details}",
            "evidence": judge_result.evidence,
            "latency_ms": round(elapsed_ms, 1),
            "num_tool_calls": 0,
            "tools_used": [],
            "error": error,
            "model": f"{model}::raw",
            "mode": "raw",
        }
        status = "PASS" if judge_result.passed else "FAIL"
        self._log(f"  -> RAW {status} (score={judge_result.score:.2f}) {judge_result.details[:60]}")
        return result

    def _run_single_task(self, task: Task, model: str) -> Dict:
        """Run one task and return the result dict."""
        self._log(f"[{task.id}] {task.category.value}: {task.input[:60]}...")

        # Clear receipts for isolation
        self._clear_receipts()

        # Snapshot token stats before
        try:
            from nally.agent.context import context_manager
            stats_before = context_manager.get_stats()
            self.cost_tracker.snapshot(task.id, stats_before)
        except Exception:
            stats_before = {}

        agent = self._create_agent(model_override=model if len(self.models) > 1 else None)
        if agent is None:
            return self._error_result(task, "Failed to create agent")

        start_time = time.time()
        response = ""
        error = None
        receipts = []
        verification_result = None

        try:
            response = agent.process(task.input)
        except Exception as e:
            error = str(e)
            response = f"Error: {e}"
            traceback.print_exc()

        elapsed_ms = (time.time() - start_time) * 1000

        # Collect receipts
        try:
            from nally.tools.receipts import receipt_store
            receipts = receipt_store.get_recent(limit=50)
        except Exception:
            receipts = []

        # Run claim verifier
        try:
            from nally.agent.verifier import ClaimVerifier
            from nally.tools.registry import registry
            verifier = ClaimVerifier()
            registered_tools = set(registry._tools.keys()) if hasattr(registry, '_tools') else set()
            verification_result = verifier.verify(
                response, receipts, registered_tools=registered_tools
            )
        except Exception:
            verification_result = None

        # Snapshot token stats after
        try:
            from nally.agent.context import context_manager
            stats_after = context_manager.get_stats()
        except Exception:
            stats_after = {}

        # Record cost
        tool_latencies = [r.duration_ms for r in receipts if hasattr(r, 'duration_ms')]
        self.cost_tracker.record_task(
            task_id=task.id,
            model=model,
            stats_after=stats_after,
            latency_ms=elapsed_ms,
            tool_latencies_ms=tool_latencies,
            num_tool_calls=len(receipts),
        )

        # Run judge
        judge_result = run_judge(task, receipts, response, verification_result)

        result = {
            "task_id": task.id,
            "category": task.category.value,
            "difficulty": task.difficulty,
            "input": task.input,
            "response": response[:2000],
            "score": judge_result.score,
            "passed": judge_result.passed,
            "details": judge_result.details,
            "evidence": judge_result.evidence,
            "latency_ms": round(elapsed_ms, 1),
            "num_tool_calls": len(receipts),
            "tools_used": [r.tool for r in receipts],
            "error": error,
            "model": model,
            "mode": "nally",
        }

        if verification_result:
            result["verification"] = verification_result.to_dict()

        status = "PASS" if judge_result.passed else "FAIL"
        self._log(f"  -> {status} (score={judge_result.score:.2f}) {judge_result.details[:60]}")

        return result

    def _error_result(self, task: Task, error: str) -> Dict:
        return {
            "task_id": task.id,
            "category": task.category.value,
            "difficulty": task.difficulty,
            "input": task.input,
            "response": "",
            "score": 0.0,
            "passed": False,
            "details": error,
            "evidence": {},
            "latency_ms": 0,
            "num_tool_calls": 0,
            "tools_used": [],
            "error": error,
            "model": "unknown",
        }

    def _run_tasks_sequential(self, tasks: List[Task], model: str, all_results: List[Dict], raw: bool = False):
        """Helper: run tasks preserving memory setup→test order."""
        memory_setup = [t for t in tasks if t.category == TaskCategory.MEMORY and t.memory_pair_id and t.memory_pair_id.startswith("setup")]
        memory_test = [t for t in tasks if t.category == TaskCategory.MEMORY and t.memory_pair_id and t.memory_pair_id.startswith("test")]
        other_tasks = [t for t in tasks if t.category != TaskCategory.MEMORY]
        fn = self._run_raw if raw else self._run_single_task
        for task in memory_setup:
            all_results.append(fn(task, model))
        for task in memory_test:
            all_results.append(fn(task, model))
        for task in other_tasks:
            all_results.append(fn(task, model))

    def run(self) -> Dict:
        """Run the full benchmark suite. Returns the JSON report."""
        tasks = self._get_tasks()
        print(f"\n{'='*60}")
        print(f"  NALLY Benchmark — {len(tasks)} tasks, {len(self.models)} model(s), mode={self.mode}")
        print(f"{'='*60}\n")

        all_results = []
        overall_start = time.time()

        for model in self.models:
            print(f"\n--- Model: {model} ---\n")
            if self.mode in ("nally", "both"):
                self._run_tasks_sequential(tasks, model, all_results, raw=False)
            if self.mode in ("raw", "both"):
                # Raw uses same tasks but no orchestration — measures lift
                if self.mode == "both":
                    print(f"\n--- Model: {model}::raw (baseline) ---\n")
                self._run_tasks_sequential(tasks, model, all_results, raw=True)

        elapsed_s = time.time() - overall_start

        # Generate reports (with NALLY Lift if mode==both)
        report = generate_json_report(all_results, self.cost_tracker, self.models, elapsed_s, mode=self.mode)
        json_path = write_json_report(report, self.output_dir)
        md_content = generate_markdown_report(report)
        md_path = write_markdown_report(md_content, self.output_dir)

        print(f"\n{'='*60}")
        print(f"  Benchmark Complete!")
        print(f"  Overall: {report['overall']['avg_score']*100:.1f}% avg, "
              f"{report['overall']['pass_rate']*100:.0f}% pass rate")
        print(f"  JSON: {json_path}")
        print(f"  Markdown: {md_path}")
        print(f"{'='*60}\n")

        return report


def main():
    parser = argparse.ArgumentParser(description="NALLY Benchmark Suite")
    parser.add_argument(
        "--models", nargs="+", default=None,
        help="Models to test (default: current model)",
    )
    parser.add_argument(
        "--tasks", nargs="+", default=None,
        help="Task categories to run (default: all)",
    )
    parser.add_argument(
        "--output", default="tests/benchmark/results",
        help="Output directory for reports",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-task output",
    )
    parser.add_argument(
        "--mode", choices=["nally","raw","both"], default="nally",
        help="Run mode: nally (default), raw (baseline), or both (paired NALLY Lift)",
    )
    parser.add_argument(
        "--pilot", type=int, default=None,
        help="If set, run pilot N tasks stratified (for human inspection gate)",
    )
    args = parser.parse_args()

    categories = None
    if args.tasks:
        categories = []
        for t in args.tasks:
            try:
                categories.append(TaskCategory(t))
            except ValueError:
                print(f"Unknown category: {t}")
                print(f"Available: {[c.value for c in TaskCategory]}")
                sys.exit(1)

    # Pilot mode: sample N tasks stratified across categories for Phase 2 gate
    if args.pilot is not None:
        from .cases import ALL_TASKS as _ALL
        import random as _rnd
        _rnd.seed(42)
        # Stratified sample: 12-14 per category for ~100
        by_cat = {}
        for t in _ALL:
            by_cat.setdefault(t.category, []).append(t)
        sampled = []
        per_cat = max(1, args.pilot // len(by_cat))
        for cat, lst in by_cat.items():
            k = min(len(lst), per_cat)
            sampled.extend(_rnd.sample(lst, k))
        # Fill remainder
        remaining = _ALL.copy()
        for t in sampled:
            if t in remaining:
                remaining.remove(t)
        while len(sampled) < args.pilot and remaining:
            sampled.append(_rnd.choice(remaining))
            remaining.remove(sampled[-1])
        # Patch ALL_TASKS for this run
        import tests.benchmark.cases as _cases
        _cases.ALL_TASKS = sampled
        print(f"[pilot] Sampled {len(sampled)} tasks stratified")

    suite = BenchmarkSuite(
        models=args.models,
        categories=categories,
        output_dir=args.output,
        verbose=not args.quiet,
        mode=args.mode,
    )
    suite.run()


if __name__ == "__main__":
    main()
