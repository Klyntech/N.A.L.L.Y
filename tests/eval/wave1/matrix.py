"""
Wave 1 — Full Matrix Orchestrator

Frozen: 80 worlds, provider separation, budgets, temperatures, seeds,
tool/context controls, trajectory logging, scorer/minefield rules.

This orchestrator CONSUMES the immutable substrate (tests/eval/suite_*)
via Wave1Runner and the thin provider adapters. It never writes to the
substrate, never mutates config, and never reinterprets mid-run.

Execution order: E-H1 -> E-H2 -> E-H3 -> E-H5 -> E-H10
Each experiment logs per-provider, per-arm ExperimentSummary JSONs
to tests/eval/wave1/results/ with config fingerprint 9b413a18.

Usage:
  python -m tests.eval.wave1.matrix --experiment E-H1 --provider opencode/hy3-free
  python -m tests.eval.wave1.matrix --all --dry-run
  python -m tests.eval.wave1.matrix --all  # full matrix (both providers)
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Dict, List

from tests.eval.wave1.config import FROZEN, EXPERIMENTS, DEFAULT_TEMPERATURE, SC_TEMPERATURE
from tests.eval.wave1.runner import Wave1Runner

# Adapter imports — thin integrations only
try:
    from tests.eval.wave1.adapters.opencode import adapter as opencode_adapter
except Exception:
    opencode_adapter = None

try:
    from tests.eval.wave1.adapters.groq import adapter as groq_adapter
except Exception:
    groq_adapter = None


ADAPTERS = {
    "opencode/hy3-free": opencode_adapter,
    "groq/llama-3.3": groq_adapter,
}

MATRIX = {
    "E-H1": {
        "arms": [
            {"arm": "act_only", "tool_set": "task", "context": "current", "temp": DEFAULT_TEMPERATURE, "note": "thoughts stripped (simulated via degraded prompt)"},
            {"arm": "react_sparse", "tool_set": "task", "context": "current", "temp": DEFAULT_TEMPERATURE, "note": "model-decided sparse thoughts"},
            {"arm": "react_dense", "tool_set": "task", "context": "current", "temp": DEFAULT_TEMPERATURE, "note": "thought each step"},
            {"arm": "react_fallback", "tool_set": "task", "context": "current", "temp": DEFAULT_TEMPERATURE, "note": "react + direct fallback"},
        ]
    },
    "E-H2": {
        "arms": [
            {"arm": "filtered_core", "tool_set": "filtered_core", "context": "current", "temp": DEFAULT_TEMPERATURE},
            {"arm": "full_registry", "tool_set": "full_registry", "context": "current", "temp": DEFAULT_TEMPERATURE},
            {"arm": "usefulness_gated", "tool_set": "task", "context": "current", "temp": DEFAULT_TEMPERATURE},
        ],
        "stress": ["clean", "scrambled"],
    },
    "E-H3": {
        "arms": [
            {"arm": "current-docs10", "tool_set": "task", "context": "current", "temp": DEFAULT_TEMPERATURE, "budget_docs": 10},
            {"arm": "current-docs20", "tool_set": "task", "context": "current", "temp": DEFAULT_TEMPERATURE, "budget_docs": 20},
            {"arm": "current-docs30", "tool_set": "task", "context": "current", "temp": DEFAULT_TEMPERATURE, "budget_docs": 30},
            {"arm": "retrieved_first-docs20", "tool_set": "task", "context": "retrieved_first", "temp": DEFAULT_TEMPERATURE, "budget_docs": 20},
            {"arm": "retrieved_last-docs20", "tool_set": "task", "context": "retrieved_last", "temp": DEFAULT_TEMPERATURE, "budget_docs": 20},
            {"arm": "query_both_ends_reranked-docs20", "tool_set": "task", "context": "query_both_ends_reranked", "temp": DEFAULT_TEMPERATURE, "budget_docs": 20},
        ]
    },
    "E-H5": {
        "arms": [
            {"arm": "blind_retry", "tool_set": "task", "context": "current", "temp": DEFAULT_TEMPERATURE},
            {"arm": "gated_retry", "tool_set": "task", "context": "current", "temp": DEFAULT_TEMPERATURE},
        ]
    },
    "E-H10": {
        "arms": [
            {"arm": "single", "tool_set": "task", "context": "current", "temp": DEFAULT_TEMPERATURE},
            {"arm": "single_plus_verifier", "tool_set": "task", "context": "current", "temp": DEFAULT_TEMPERATURE},
            {"arm": "sc3", "tool_set": "task", "context": "current", "temp": SC_TEMPERATURE},
            {"arm": "sc5", "tool_set": "task", "context": "current", "temp": SC_TEMPERATURE},
        ]
    },
}


def _adapter_for(provider: str):
    a = ADAPTERS.get(provider)
    if a is None:
        raise ValueError(f"No adapter for provider {provider}. Available: {list(ADAPTERS)}")
    return a


def run_experiment(experiment_id: str, provider: str, dry_run: bool = False) -> List[Dict]:
    if experiment_id not in MATRIX:
        raise ValueError(f"Unknown experiment {experiment_id}")
    spec = MATRIX[experiment_id]
    arms = spec["arms"]
    results = []
    adapter = _adapter_for(provider)
    for arm_spec in arms:
        arm = arm_spec["arm"]
        print(f"[{experiment_id}][{provider}][{arm}] starting (dry_run={dry_run})")
        if dry_run:
            results.append({"experiment": experiment_id, "provider": provider, "arm": arm, "dry_run": True})
            continue
        runner = Wave1Runner(
            experiment_id=experiment_id,
            arm=arm,
            provider=provider,
            tool_set_mode=arm_spec.get("tool_set", "task"),
            context_placement=arm_spec.get("context", "current"),
            temperature=arm_spec.get("temp", DEFAULT_TEMPERATURE),
        )
        summary = runner.run(adapter=adapter, write=True)
        results.append({"experiment": experiment_id, "provider": provider, "arm": arm, "mean_score": summary.mean_score, "total": summary.total})
        print(f"  -> mean {summary.mean_score} total {summary.total}")
        # Small delay to respect rate limits
        time.sleep(0.5)
    return results


def run_all(dry_run: bool = False, providers: List[str] = None, experiments: List[str] = None):
    providers = providers or [p["id"] for p in FROZEN.providers]
    experiments = experiments or list(MATRIX.keys())
    all_results = []
    for exp in experiments:
        for prov in providers:
            res = run_experiment(exp, prov, dry_run=dry_run)
            all_results.extend(res)
    return all_results


def main():
    parser = argparse.ArgumentParser(description="Wave 1 Matrix Orchestrator")
    parser.add_argument("--experiment", type=str, help="Single experiment (E-H1..E-H10)")
    parser.add_argument("--provider", type=str, help="Single provider")
    parser.add_argument("--all", action="store_true", help="Run full matrix")
    parser.add_argument("--dry-run", action="store_true", help="Validate without LLM calls")
    parser.add_argument("--list", action="store_true", help="List matrix and exit")
    args = parser.parse_args()

    if args.list:
        print(json.dumps(MATRIX, indent=2))
        return

    if args.all:
        res = run_all(dry_run=args.dry_run)
        print(json.dumps(res, indent=2))
        return

    if args.experiment and args.provider:
        res = run_experiment(args.experiment, args.provider, dry_run=args.dry_run)
        print(json.dumps(res, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
