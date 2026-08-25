"""Task definitions for the NALLY benchmark.

30 tasks across 6 categories. Each task specifies:
  - input: the user message
  - category: which metric it tests
  - expected_tools: which tools should be called (for tool selection scoring)
  - expected_steps: for multi-step tasks, the minimum tool calls needed
  - should_fail_tool: if set, this tool name will fail (for recovery testing)
  - validation: optional callable(response, receipts) -> bool for correctness
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional


class TaskCategory(str, Enum):
    TOOL_SELECTION = "tool_selection"
    MULTI_STEP = "multi_step"
    FAILURE_RECOVERY = "failure_recovery"
    FALSE_CLAIMS = "false_claims"
    MEMORY = "memory"
    AUTONOMOUS_CODING = "autonomous_coding"
    ADVERSARIAL = "adversarial"
    LONG_HORIZON = "long_horizon"


# ── Bucket definitions (for reporting) ────────────────────
# Keep adversarial/long-horizon separate per user request — don't hide behind aggregate.

BUCKETS: dict[str, list[TaskCategory]] = {
    "Reliability": [TaskCategory.TOOL_SELECTION, TaskCategory.FAILURE_RECOVERY, TaskCategory.FALSE_CLAIMS],
    "Capability": [TaskCategory.MULTI_STEP, TaskCategory.AUTONOMOUS_CODING, TaskCategory.LONG_HORIZON, TaskCategory.MEMORY],
    "Safety": [TaskCategory.ADVERSARIAL],
}

# Overall is secondary — computed as mean of bucket means, not raw task mean.


@dataclass
class Task:
    id: str
    input: str
    category: TaskCategory
    expected_tools: List[str] = field(default_factory=list)
    expected_min_steps: int = 1
    should_fail_tool: Optional[str] = None
    difficulty: str = "medium"
    description: str = ""
    validation: Optional[Callable] = None
    memory_pair_id: Optional[str] = None  # links memory tasks (setup -> test)
    # ── Extended fields for adversarial / long-horizon (Phase 1) ──
    is_adversarial: bool = False
    adversarial_subtype: Optional[str] = None  # A1..A7
    requires_plan: bool = False
    wall_time: int = 300  # per-task override (long-horizon needs 900-1200)
    setup_ids: List[str] = field(default_factory=list)  # for multi-turn long-horizon


# ── Tool Selection (5 tasks) ──────────────────────────────

TOOL_SELECTION_TASKS = [
    Task(
        id="ts_001",
        input="What's the current weather in Lagos, Nigeria?",
        category=TaskCategory.TOOL_SELECTION,
        expected_tools=["web_search"],
        difficulty="easy",
        description="Should use web_search for live weather data",
    ),
    Task(
        id="ts_002",
        input="Read the file nally/config.py and tell me what PROVIDER is set to",
        category=TaskCategory.TOOL_SELECTION,
        expected_tools=["read_file"],
        difficulty="easy",
        description="Should use read_file to inspect a local file",
    ),
    Task(
        id="ts_003",
        input="Create a new file called test_output.txt with the content 'Hello from NALLY benchmark'",
        category=TaskCategory.TOOL_SELECTION,
        expected_tools=["file_ops"],
        difficulty="easy",
        description="Should use file_ops to create a file",
    ),
    Task(
        id="ts_004",
        input="Run the command 'python --version' and tell me the output",
        category=TaskCategory.TOOL_SELECTION,
        expected_tools=["run_command"],
        difficulty="easy",
        description="Should use run_command to execute a shell command",
    ),
    Task(
        id="ts_005",
        input="Generate an image of a sunset over the ocean",
        category=TaskCategory.TOOL_SELECTION,
        expected_tools=["generate_image"],
        difficulty="medium",
        description="Should use generate_image for image creation",
    ),
]

# ── Multi-Step (5 tasks) ──────────────────────────────────

MULTI_STEP_TASKS = [
    Task(
        id="ms_001",
        input="Read the file nally/config.py, find the line with MAX_ITERATIONS, and tell me the current value",
        category=TaskCategory.MULTI_STEP,
        expected_tools=["read_file"],
        expected_min_steps=1,
        difficulty="easy",
        description="Read file + extract info (2 logical steps, 1 tool call)",
    ),
    Task(
        id="ms_002",
        input="Create a Python file called bench_math.py that defines a function add(a, b) returning a+b, then run it with python -c 'from bench_math import add; print(add(3, 5))'",
        category=TaskCategory.MULTI_STEP,
        expected_tools=["file_ops", "run_command"],
        expected_min_steps=2,
        difficulty="medium",
        description="Create file + run command = 2 sequential tool calls",
    ),
    Task(
        id="ms_003",
        input="Search the web for 'Python 3.13 release date', then create a file called python_release.txt with the answer",
        category=TaskCategory.MULTI_STEP,
        expected_tools=["web_search", "file_ops"],
        expected_min_steps=2,
        difficulty="medium",
        description="Web search + file creation = 2 sequential calls",
    ),
    Task(
        id="ms_004",
        input="List all .py files in the current directory, then count how many there are and tell me",
        category=TaskCategory.MULTI_STEP,
        expected_tools=["run_command"],
        expected_min_steps=1,
        difficulty="easy",
        description="Run ls + parse output",
    ),
    Task(
        id="ms_005",
        input="Read nally/config.py, extract all environment variable names, then create a file env_vars.txt listing them one per line",
        category=TaskCategory.MULTI_STEP,
        expected_tools=["read_file", "file_ops"],
        expected_min_steps=2,
        difficulty="hard",
        description="Read + parse + write = 3 logical steps",
    ),
]

# ── Failure Recovery (5 tasks) ────────────────────────────

FAILURE_RECOVERY_TASKS = [
    Task(
        id="fr_001",
        input="Run the command 'nonexistent_command_xyz123'",
        category=TaskCategory.FAILURE_RECOVERY,
        expected_tools=["run_command"],
        difficulty="easy",
        description="Command will fail — should report error, not hallucinate success",
    ),
    Task(
        id="fr_002",
        input="Read the file /nonexistent/path/that/does/not/exist.txt",
        category=TaskCategory.FAILURE_RECOVERY,
        expected_tools=["read_file"],
        difficulty="easy",
        description="File doesn't exist — should report error gracefully",
    ),
    Task(
        id="fr_003",
        input="Delete the file bench_nonexistent_delete_test.txt using file_ops",
        category=TaskCategory.FAILURE_RECOVERY,
        expected_tools=["file_ops"],
        difficulty="medium",
        description="Delete non-existent file — should report error",
    ),
    Task(
        id="fr_004",
        input="Run 'python -c \"import sys; sys.exit(1)\"' and tell me what happened",
        category=TaskCategory.FAILURE_RECOVERY,
        expected_tools=["run_command"],
        difficulty="medium",
        description="Command exits with code 1 — should detect failure",
    ),
    Task(
        id="fr_005",
        input="Run 'curl http://localhost:19999/nonexistent' to test a connection",
        category=TaskCategory.FAILURE_RECOVERY,
        expected_tools=["run_command"],
        difficulty="hard",
        description="Connection will fail — should handle timeout/error",
    ),
]

# ── False Claims (5 tasks) ────────────────────────────────

FALSE_CLAIMS_TASKS = [
    Task(
        id="fc_001",
        input="Tell me the output of running 'echo hello_world_benchmark'",
        category=TaskCategory.FALSE_CLAIMS,
        expected_tools=["run_command"],
        difficulty="medium",
        description="Should actually run the command, not guess the output",
    ),
    Task(
        id="fc_002",
        input="What's the first line of nally/config.py?",
        category=TaskCategory.FALSE_CLAIMS,
        expected_tools=["read_file"],
        difficulty="medium",
        description="Should actually read the file, not guess the content",
    ),
    Task(
        id="fc_003",
        input="Run 'date' and tell me the exact output",
        category=TaskCategory.FALSE_CLAIMS,
        expected_tools=["run_command"],
        difficulty="medium",
        description="Should run date command, not make up a timestamp",
    ),
    Task(
        id="fc_004",
        input="Read nally/config.py and tell me the exact value of MAX_TOOL_CALLS",
        category=TaskCategory.FALSE_CLAIMS,
        expected_tools=["read_file"],
        difficulty="medium",
        description="Should read file for exact value, not guess from training data",
    ),
    Task(
        id="fc_005",
        input="Run 'python --version' and copy the exact output including the version number",
        category=TaskCategory.FALSE_CLAIMS,
        expected_tools=["run_command"],
        difficulty="medium",
        description="Should run command for exact version, not hallucinate",
    ),
]

# ── Memory (5 tasks — 2 setup + 3 test) ───────────────────

MEMORY_TASKS = [
    Task(
        id="mem_001",
        input="Remember that my favorite programming language is Rust and my favorite editor is Neovim",
        category=TaskCategory.MEMORY,
        expected_tools=[],
        difficulty="easy",
        description="Setup: store user preferences in memory",
        memory_pair_id="setup_1",
    ),
    Task(
        id="mem_002",
        input="Remember that I'm currently working on a project called NALLY which is an AI assistant",
        category=TaskCategory.MEMORY,
        expected_tools=[],
        difficulty="easy",
        description="Setup: store project context in memory",
        memory_pair_id="setup_2",
    ),
    Task(
        id="mem_003",
        input="What's my favorite programming language?",
        category=TaskCategory.MEMORY,
        expected_tools=[],
        difficulty="easy",
        description="Test: should recall 'Rust' from memory",
        memory_pair_id="test_lang",
        validation=lambda resp, _: "rust" in resp.lower(),
    ),
    Task(
        id="mem_004",
        input="What project am I working on?",
        category=TaskCategory.MEMORY,
        expected_tools=[],
        difficulty="easy",
        description="Test: should recall 'NALLY' from memory",
        memory_pair_id="test_project",
        validation=lambda resp, _: "nally" in re.sub(r"[^a-z]", "", resp.lower()),
    ),
    Task(
        id="mem_005",
        input="What's my favorite editor and what project am I working on?",
        category=TaskCategory.MEMORY,
        expected_tools=[],
        difficulty="medium",
        description="Test: should recall both Neovim and NALLY",
        memory_pair_id="test_combined",
        validation=lambda resp, _: "neovim" in re.sub(r"[^a-z]", "", resp.lower()) and "nally" in re.sub(r"[^a-z]", "", resp.lower()),
    ),
]

# ── Autonomous Coding (5 tasks) ───────────────────────────

AUTONOMOUS_CODING_TASKS = [
    Task(
        id="ac_001",
        input="Write a Python function called factorial(n) that computes the factorial of n recursively. Save it to bench_factorial.py and test it with factorial(5) which should equal 120",
        category=TaskCategory.AUTONOMOUS_CODING,
        expected_tools=["file_ops", "run_command"],
        expected_min_steps=2,
        difficulty="medium",
        description="Write function + create file + test it",
        validation=lambda resp, _: "120" in resp,
    ),
    Task(
        id="ac_002",
        input="Create a bash script called bench_fizzbuzz.sh that prints numbers 1-20 but replaces multiples of 3 with Fizz, multiples of 5 with Buzz, and multiples of both with FizzBuzz. Then run it",
        category=TaskCategory.AUTONOMOUS_CODING,
        expected_tools=["file_ops", "run_command"],
        expected_min_steps=2,
        difficulty="medium",
        description="FizzBuzz script + execute",
        validation=lambda resp, _: "FizzBuzz" in resp and "16" in resp,
    ),
    Task(
        id="ac_003",
        input="Write a Python script bench_palindrome.py that checks if a string is a palindrome (case-insensitive, ignoring spaces). Include test cases for 'racecar', 'hello', and 'A man a plan a canal Panama'. Run the tests",
        category=TaskCategory.AUTONOMOUS_CODING,
        expected_tools=["file_ops", "run_command"],
        expected_min_steps=2,
        difficulty="hard",
        description="Palindrome checker with tests",
        validation=lambda resp, _: "true" in resp.lower() or "racecar" in resp.lower(),
    ),
    Task(
        id="ac_004",
        input="Create a Python file bench_fibonacci.py that generates the first 20 Fibonacci numbers and prints them. Run it",
        category=TaskCategory.AUTONOMOUS_CODING,
        expected_tools=["file_ops", "run_command"],
        expected_min_steps=2,
        difficulty="medium",
        description="Fibonacci generator + execute",
        validation=lambda resp, _: "0" in resp and "1" in resp and "6765" in resp,
    ),
    Task(
        id="ac_005",
        input="Write a Python script bench_sort.py that implements bubble sort, then use it to sort [64, 34, 25, 12, 22, 11, 90] and print the result. Run the script",
        category=TaskCategory.AUTONOMOUS_CODING,
        expected_tools=["file_ops", "run_command"],
        expected_min_steps=2,
        difficulty="hard",
        description="Bubble sort implementation + execute",
        validation=lambda resp, _: "11" in resp and "90" in resp,
    ),
]

# ── Adversarial (100 tasks — Phase 1: templated, see generate.py) ────
# Frozen spec: 7 subtypes × 14-15. Generated tasks live in cases_generated.py.
ADVERSARIAL_TASKS: List[Task] = []

# ── Long Horizon (100 tasks — Phase 1) ────────────────────
LONG_HORIZON_TASKS: List[Task] = []

# ── All tasks combined ────────────────────────────────────

# Original 30 — FROZEN per user request (do not modify after seeing results).
FROZEN_30_IDS: set[str] = {
    t.id for t in (
        TOOL_SELECTION_TASKS
        + MULTI_STEP_TASKS
        + FAILURE_RECOVERY_TASKS
        + FALSE_CLAIMS_TASKS
        + MEMORY_TASKS
        + AUTONOMOUS_CODING_TASKS
    )
}

ALL_TASKS: List[Task] = (
    TOOL_SELECTION_TASKS
    + MULTI_STEP_TASKS
    + FAILURE_RECOVERY_TASKS
    + FALSE_CLAIMS_TASKS
    + MEMORY_TASKS
    + AUTONOMOUS_CODING_TASKS
    + ADVERSARIAL_TASKS
    + LONG_HORIZON_TASKS
)

# Merge generated tasks if present (800-task suite). Keeps 30 frozen.
try:
    from .cases_generated import GENERATED_TASKS as _GEN  # type: ignore
    # Deduplicate by id — generated must not override frozen 30
    _existing_ids = {t.id for t in ALL_TASKS}
    _new = [t for t in _GEN if t.id not in _existing_ids]
    ALL_TASKS = ALL_TASKS + _new
except ImportError:
    pass
except Exception:
    pass


def get_tasks_by_category(category: TaskCategory) -> List[Task]:
    return [t for t in ALL_TASKS if t.category == category]


def get_task_by_id(task_id: str) -> Optional[Task]:
    for t in ALL_TASKS:
        if t.id == task_id:
            return t
    return None


def get_tasks_by_difficulty(difficulty: str) -> List[Task]:
    return [t for t in ALL_TASKS if t.difficulty == difficulty]


def get_tasks_by_bucket(bucket: str) -> List[Task]:
    cats = BUCKETS.get(bucket, [])
    return [t for t in ALL_TASKS if t.category in cats]


def is_frozen(task: Task) -> bool:
    return task.id in FROZEN_30_IDS
