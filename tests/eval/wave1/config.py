"""
Wave 1 — Frozen Configuration (immutable for all E-H1/H2/H3/H5/H10 runs).

This file is the single source of truth for Wave 1 experimental controls.
Changing any value here requires a new WAVE1_CONFIG_VERSION and a fresh
data directory — never mutate in place.

Substrate is IMMUTABLE: 80 task worlds in tests/eval/suite_{t,p,a,c}/tasks
and their scorers are never modified by Wave 1 code. The runner only READS
them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Literal
import hashlib
import json

WAVE1_CONFIG_VERSION = "wave1-v1.0-frozen-2026-09-06"

# ---------------------------------------------------------------------------
# Fixed budget — pinned to nally/config.py values per Phase 2 section 0
# Never invent new limits; Wave 1 only READS these as caps.
# ---------------------------------------------------------------------------
FIXED_BUDGET = {
    "MAX_TOOL_CALLS": 50,
    "MAX_ITERATIONS_PER_TURN": 30,
    "MAX_AGENT_WALL_TIME": 300,  # seconds
    "RECURSION_LIMIT": 50,
    "MAX_TOOL_FAILURES_PER_TURN": 5,
    "TOOL_RETRY_LIMIT": 3,
    # planning
    "PLAN_MAX_STEPS": 10,
    "PLAN_MAX_REVISIONS": 3,
    "PLAN_STEP_TIMEOUT": 300,
    "PLAN_STEP_MAX_ITERATIONS": 15,
    # thinking
    "THINKING_MAX_STRATEGIES": 3,
    "THINKING_TIMEOUT": 30,
    # context (defaults; E-H3 varies within these caps, never beyond)
    "CONTEXT_MAX_TOKENS": 500_000,
    "MAX_MEMORIES_TO_INJECT": 12,
    "CONTEXT_COMPRESSION_THRESHOLD": 20,
}

# ---------------------------------------------------------------------------
# Providers — both required; results reported per-provider, never averaged
# ---------------------------------------------------------------------------
PROVIDERS: List[Dict[str, str]] = [
    {"id": "opencode/hy3-free", "label": "OpenCode hy3-free"},
    {"id": "groq/llama-3.3", "label": "Groq Llama 3.3"},
]

# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
GLOBAL_SEED = 42  # task seeds (t*.json/p*.json) remain authoritative; this seeds shuffles
DETERMINISTIC_ORDER = True  # tasks run in sorted id order; no random shuffle in v1

# ---------------------------------------------------------------------------
# Tasks — same 80 worlds; scorer is immutable
# ---------------------------------------------------------------------------
TASK_COUNTS = {
    "suite_t": 24,
    "suite_p": 26,
    "suite_a": 18,
    "suite_c": 12,
}
TOTAL_TASKS = sum(TASK_COUNTS.values())  # 80

# ---------------------------------------------------------------------------
# Temperature — fixed per experiment; SC arms override only within E-H10
# ---------------------------------------------------------------------------
DEFAULT_TEMPERATURE: float = 0.2  # deterministic greedy-like for all non-SC arms
SC_TEMPERATURE: float = 0.7  # E-H10 SC-3/SC-5 only

# ---------------------------------------------------------------------------
# Tool set — explicitly controlled per arm (E-H2); default is task-declared
# "task" means use task.available_tools verbatim (no filter, no augmentation)
# ---------------------------------------------------------------------------
ToolSetMode = Literal["task", "full_registry", "filtered_core"]
DEFAULT_TOOL_SET: ToolSetMode = "task"

# ---------------------------------------------------------------------------
# Context — explicitly controlled per arm (E-H3); default is task + fixed budget
# Valid placements are documented in docs/research/02-experiment-design.md E-H3
# ---------------------------------------------------------------------------
ContextPlacement = Literal["current", "retrieved_first", "retrieved_last", "query_both_ends_reranked"]
DEFAULT_CONTEXT_PLACEMENT: ContextPlacement = "current"

# ---------------------------------------------------------------------------
# Retries — experiment-specific, never accidental
# ---------------------------------------------------------------------------
RETRY_POLICY: Dict[str, Dict[str, int]] = {
    "E-H1": {"blind": 0, "react_fallback": 1},
    "E-H2": {"all_arms": 0},
    "E-H3": {"all_arms": 0},
    "E-H5": {"blind_retry": 1, "gated_retry": 1},  # exactly one retry, gated vs blind
    "E-H10": {"all_arms": 0},  # SC is multi-sample, not retry
}

# ---------------------------------------------------------------------------
# Trajectory logging — full enough to audit decisions
# ---------------------------------------------------------------------------
TRAJECTORY_LOG_FIELDS = [
    "provider",
    "experiment_id",
    "arm",
    "task_id",
    "suite",
    "seed",
    "tool_calls",       # list of {name, args, ok, result_truncated}
    "world_snapshots",  # optional, per turn file hash
    "scorer_output",    # {score, milestone_similarity, minefield_hits, diagnostics}
    "budget_used",      # {tool_calls, wall_ms}
    "temperature",
    "tool_set_mode",
    "context_placement",
    "timestamp",
]

# ---------------------------------------------------------------------------
# Result schema versioning
# ---------------------------------------------------------------------------
RESULT_SCHEMA_VERSION = "wave1-result-v1"


@dataclass(frozen=True)
class Wave1Config:
    version: str = WAVE1_CONFIG_VERSION
    providers: List[Dict[str, str]] = field(default_factory=lambda: list(PROVIDERS))
    budget: Dict[str, int] = field(default_factory=lambda: dict(FIXED_BUDGET))
    global_seed: int = GLOBAL_SEED
    deterministic_order: bool = DETERMINISTIC_ORDER
    task_counts: Dict[str, int] = field(default_factory=lambda: dict(TASK_COUNTS))
    total_tasks: int = TOTAL_TASKS
    default_temperature: float = DEFAULT_TEMPERATURE
    sc_temperature: float = SC_TEMPERATURE
    default_tool_set: str = DEFAULT_TOOL_SET
    default_context_placement: str = DEFAULT_CONTEXT_PLACEMENT
    retry_policy: Dict[str, Dict[str, int]] = field(default_factory=lambda: dict(RETRY_POLICY))
    result_schema_version: str = RESULT_SCHEMA_VERSION

    def fingerprint(self) -> str:
        """Deterministic hash of the frozen config — written into every result file."""
        payload = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


# Singleton frozen instance
FROZEN = Wave1Config()

# ---------------------------------------------------------------------------
# Experiment registry — five Wave 1 experiments as specified
# ---------------------------------------------------------------------------
EXPERIMENTS = {
    "E-H1": {
        "title": "ReAct loop variants",
        "arms": ["act_only", "react_sparse", "react_dense", "react_fallback"],
        "primary_harness": "suite_t + suite_a (15 tasks, multi-step)",
        "temperature": DEFAULT_TEMPERATURE,
    },
    "E-H2": {
        "title": "Tool filtering (3 arms + scrambling stress)",
        "arms": ["filtered_core", "full_registry", "usefulness_gated"],
        "stress": ["clean", "scrambled"],
        "primary_harness": "suite_t + suite_a (14 tasks, chain/dependency/canonical)",
        "temperature": DEFAULT_TEMPERATURE,
    },
    "E-H3": {
        "title": "Context placement x budget",
        "arms_placement": ["current", "retrieved_first", "retrieved_last", "query_both_ends_reranked"],
        "arms_budget": ["docs10", "docs20", "docs30"],
        "primary_harness": "suite_t + suite_c (placement-sensitive, 15 task-forms)",
        "temperature": DEFAULT_TEMPERATURE,
    },
    "E-H5": {
        "title": "Reflection: gated vs blind retry",
        "arms": ["blind_retry", "gated_retry"],
        "primary_harness": "suite_t recoverable-failure subset (10+2 bottleneck controls)",
        "temperature": DEFAULT_TEMPERATURE,
    },
    "E-H10": {
        "title": "Verification vs SC-3/SC-5 + consistency calibration",
        "arms": ["single", "single_plus_verifier", "sc3", "sc5"],
        "harness_split": ["reasoning_no_receipt", "grounded_with_receipt", "ambiguous_ask_gate"],
        "primary_harness": "suite_t + suite_p + suite_a (22 tasks split)",
        "temperature": "0.2 for single arms, 0.7 for sc3/sc5",
    },
}
