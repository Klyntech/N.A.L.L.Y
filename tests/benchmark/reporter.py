"""Reporter — generates JSON + Markdown benchmark report."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from .cases import Task, TaskCategory
from .cost import CostTracker


def _bar(score: float, width: int = 20) -> str:
    filled = int(score * width)
    return f"{'█' * filled}{'░' * (width - filled)}"


def _pct(score: float) -> str:
    return f"{score * 100:.1f}%"


def generate_json_report(
    results: List[Dict],
    cost_tracker: CostTracker,
    models: List[str],
    elapsed_s: float,
    mode: str = "nally",
) -> Dict:
    """Build the full JSON report structure."""
    # Aggregate by category
    by_category: Dict[str, List[Dict]] = {}
    for r in results:
        cat = r["category"]
        by_category.setdefault(cat, []).append(r)

    category_summaries = {}
    for cat, cat_results in by_category.items():
        scores = [r["score"] for r in cat_results]
        category_summaries[cat] = {
            "tasks": len(cat_results),
            "avg_score": sum(scores) / len(scores) if scores else 0,
            "min_score": min(scores) if scores else 0,
            "max_score": max(scores) if scores else 0,
            "passed": sum(1 for r in cat_results if r["passed"]),
            "failed": sum(1 for r in cat_results if not r["passed"]),
        }

    # Buckets: Reliability / Capability / Safety (overall is secondary)
    try:
        from .cases import BUCKETS
        buckets = {}
        for bucket_name, cats in BUCKETS.items():
            cat_names = [c.value for c in cats]
            bucket_results = [r for r in results if r["category"] in cat_names]
            if bucket_results:
                scores = [r["score"] for r in bucket_results]
                buckets[bucket_name] = {
                    "tasks": len(bucket_results),
                    "avg_score": sum(scores) / len(scores) if scores else 0,
                    "pass_rate": sum(1 for r in bucket_results if r["passed"]) / len(bucket_results) if bucket_results else 0,
                    "categories": cat_names,
                }
            else:
                buckets[bucket_name] = {"tasks": 0, "avg_score": 0, "pass_rate": 0, "categories": cat_names}
    except Exception:
        buckets = {}

    # Frozen 30 separate (never modified after seeing results)
    try:
        from .cases import FROZEN_30_IDS
        frozen_results = [r for r in results if r["task_id"] in FROZEN_30_IDS]
        if frozen_results:
            f_scores = [r["score"] for r in frozen_results]
            frozen_summary = {
                "tasks": len(frozen_results),
                "avg_score": sum(f_scores) / len(f_scores) if f_scores else 0,
                "pass_rate": sum(1 for r in frozen_results if r["passed"]) / len(frozen_results) if frozen_results else 0,
            }
        else:
            frozen_summary = None
    except Exception:
        frozen_summary = None

    # NALLY Lift = NALLY - Raw (paired, same task, same model)
    lift = None
    if mode == "both":
        # Group by (task_id, model_base) where model is "opencode/hy3-free" and "opencode/hy3-free::raw"
        from collections import defaultdict
        paired = defaultdict(dict)  # (task_id, base_model) -> {nally: score, raw: score}
        for r in results:
            mid = r.get("model", "")
            base = mid.replace("::raw", "")
            m = r.get("mode", "nally" if "::raw" not in mid else "raw")
            key = (r["task_id"], base)
            paired[key][m] = r["score"]
        lifts = []
        for (tid, base), scores in paired.items():
            if "nally" in scores and "raw" in scores:
                lifts.append(scores["nally"] - scores["raw"])
        if lifts:
            lift = {
                "paired_tasks": len(lifts),
                "avg_lift": sum(lifts) / len(lifts) if lifts else 0,
                "nally_avg": sum(paired[k]["nally"] for k in paired if "nally" in paired[k] and "raw" in paired[k]) / len(lifts) if lifts else 0,
                "raw_avg": sum(paired[k]["raw"] for k in paired if "nally" in paired[k] and "raw" in paired[k]) / len(lifts) if lifts else 0,
            }

    overall_scores = [r["score"] for r in results]
    overall_passed = sum(1 for r in results if r["passed"])

    report = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_tasks": len(results),
            "models_tested": models,
            "elapsed_seconds": round(elapsed_s, 1),
            "mode": mode,
        },
        "overall": {
            "avg_score": sum(overall_scores) / len(overall_scores) if overall_scores else 0,
            "pass_rate": overall_passed / len(results) if results else 0,
            "total_passed": overall_passed,
            "total_failed": len(results) - overall_passed,
            "note": "Overall is secondary — see buckets for primary metrics",
        },
        "by_category": category_summaries,
        "buckets": buckets,
        "frozen_30": frozen_summary,
        "cost": cost_tracker.to_dict(),
        "task_results": results,
    }
    if lift is not None:
        report["nally_lift"] = lift
    return report


def write_json_report(report: Dict, output_dir: str) -> str:
    """Write JSON report to disk. Returns file path."""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"benchmark_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    return path


def generate_markdown_report(report: Dict) -> str:
    """Generate a Markdown summary from the JSON report."""
    lines = []
    meta = report["meta"]
    overall = report["overall"]
    categories = report["by_category"]
    cost = report.get("cost", {})
    buckets = report.get("buckets", {})
    lift = report.get("nally_lift")
    frozen = report.get("frozen_30")

    lines.append("# NALLY Benchmark Report")
    lines.append("")
    lines.append(f"**Date**: {meta['timestamp']}")
    lines.append(f"**Models**: {', '.join(meta['models_tested'])}")
    lines.append(f"**Mode**: {meta.get('mode','nally')}")
    lines.append(f"**Tasks**: {meta['total_tasks']}")
    lines.append(f"**Duration**: {meta['elapsed_seconds']}s")
    if frozen:
        lines.append(f"**Frozen 30**: {_pct(frozen['avg_score'])} ({frozen['tasks']} tasks) — never modified after seeing results")
    lines.append("")

    # Buckets (primary — per user request)
    if buckets:
        lines.append("## Buckets (Primary Metrics)")
        lines.append("")
        lines.append("> Overall is secondary — buckets reveal if 98% tool-selection hides 40% long-horizon failure.")
        lines.append("")
        lines.append("| Bucket | Tasks | Avg Score | Pass Rate | Categories |")
        lines.append("|--------|-------|-----------|-----------|------------|")
        for bname in ["Reliability","Capability","Safety"]:
            b = buckets.get(bname)
            if b:
                cats = ", ".join(b.get("categories", []))
                lines.append(f"| **{bname}** | {b['tasks']} | {_pct(b['avg_score'])} | {_pct(b['pass_rate'])} | {cats} |")
        lines.append("")

    # NALLY Lift (most important experiment)
    if lift:
        lines.append("## NALLY Lift (NALLY − Raw, Paired)")
        lines.append("")
        lines.append(f"> Same task, same model, same params — does NALLY architecture help?")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Paired tasks | {lift['paired_tasks']} |")
        lines.append(f"| NALLY avg | {_pct(lift['nally_avg'])} |")
        lines.append(f"| Raw avg | {_pct(lift['raw_avg'])} |")
        lines.append(f"| **Lift** | **{_pct(lift['avg_lift'])}** |")
        lines.append(f"| Lift = NALLY − Raw | `{lift['avg_lift']:+.3f}` |")
        lines.append("")

    # Overall (secondary)
    lines.append("## Overall (Secondary)")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Average Score | {_pct(overall['avg_score'])} |")
    lines.append(f"| Pass Rate | {_pct(overall['pass_rate'])} |")
    lines.append(f"| Passed | {overall['total_passed']} |")
    lines.append(f"| Failed | {overall['total_failed']} |")
    lines.append("")

    # By category
    lines.append("## Results by Category")
    lines.append("")
    lines.append("| Category | Tasks | Avg Score | Passed | Failed |")
    lines.append("|----------|-------|-----------|--------|--------|")
    for cat, s in sorted(categories.items()):
        lines.append(
            f"| {cat} | {s['tasks']} | {_pct(s['avg_score'])} | {s['passed']} | {s['failed']} |"
        )
    lines.append("")

    # Category breakdown
    lines.append("## Score Breakdown")
    lines.append("")
    for cat, s in sorted(categories.items()):
        lines.append(f"### {cat}")
        lines.append(f"```")
        lines.append(f"Score: {_bar(s['avg_score'])} {_pct(s['avg_score'])}")
        lines.append(f"Range: {_pct(s['min_score'])} – {_pct(s['max_score'])}")
        lines.append(f"```")
        lines.append("")

    # Cost
    model_costs = cost.get("models", {})
    if model_costs:
        lines.append("## Token Usage")
        lines.append("")
        lines.append("| Model | Tasks | Total Tokens | Avg/Task | Avg Latency |")
        lines.append("|-------|-------|-------------|----------|-------------|")
        for model, mc in model_costs.items():
            lines.append(
                f"| {model} | {mc['tasks_run']} | {mc['total_tokens']:,} "
                f"| {mc['avg_tokens_per_task']:,.0f} | {mc['avg_latency_ms']:.0f}ms |"
            )
        lines.append("")

    # Failed tasks detail
    failed = [r for r in report.get("task_results", []) if not r.get("passed")]
    if failed:
        lines.append("## Failed Tasks")
        lines.append("")
        lines.append("| Task ID | Category | Score | Details |")
        lines.append("|---------|----------|-------|---------|")
        for r in failed[:50]:  # cap at 50 for 800-task report
            details = r.get("details", "")[:80]
            mode = r.get("mode","")
            mid = f" {mode}" if mode else ""
            lines.append(f"| {r['task_id']}{mid} | {r['category']} | {_pct(r['score'])} | {details} |")
        if len(failed) > 50:
            lines.append(f"| ... | ... | ... | +{len(failed)-50} more |")
        lines.append("")

    return "\n".join(lines)


def write_markdown_report(content: str, output_dir: str) -> str:
    """Write Markdown report to disk. Returns file path."""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"benchmark_{ts}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
