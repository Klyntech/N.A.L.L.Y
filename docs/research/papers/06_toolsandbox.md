# 06 — ToolSandbox: A Stateful, Conversational, Interactive Evaluation Benchmark (Lu et al., 2024)

Source: https://arxiv.org/abs/2408.04682 (v1; HTML v1 inspected, §§1–4)

## Finding (1–2 sentences)

Tool use must be evaluated as **stateful** (world-state + implicit tool dependencies), **conversational** (on-policy user simulator, multi-turn ambiguity), and **interactive** (exceptions, corrections, trial-and-error) with milestone/minefield scoring over arbitrary trajectories — single-turn stateless benchmarks systematically miss the hard cases (state dependency, canonicalization, insufficient-information).

## Evidence strength

- 1032 human-authored cases (2 experts: author + validator-agent), 34 composable Python + wrapped RapidAPI tools, avg 13.9 turns / 3.8 tool calls per dialog (vs BFCL 2.0/0.78, ToolEval 7.53/1.46, API-Bank 3.88/2.04).
- Design: Execution Context (world state) + Message Bus (User/Agent/Environment views) + Milestones (must-happen DAG, similarity 0–1, topological match) + Minefields (must-NOT-happen; violation zeroes score) + turn-count efficiency metric; race-condition penalty for parallel calls on dependent tools.
- Results: proprietary >> open-source (best open Hermes-Mistral-7B >20pp behind Claude-3-Haiku); GPT-4o top (73.0 avg), then Opus 69.2; hard categories: State Dependency, Canonicalization, Insufficient Info challenge even SOTA. Notable: larger models *worse* at State Dependency (GPT-4/Opus parallel-call on dependent tools despite race penalty); time canonicalization (timestamps, relative dates) frequently hallucinated; insufficient-info rewards *not* calling (open models score spuriously high by never calling).
- User simulator (GPT-4o + Knowledge Boundary + Demonstration) validated to lowest hallucination/IF error; error consistency checked across agents.
- Strength: milestone DAG allows any valid trajectory (different tools/order/retries) to score; minefields catch hallucinating-when-unsolvable. Weakness: Apple-authored domains, GPT-4o simulator bias, similarity-metric judgment calls; no cost-normalized leaderboard.

## Assumptions

- Python-native tools mutating Execution Context; informative exceptions (e.g., ConnectionError when cellular off → enable-service then retry); nested dependencies possible (message→cellular→battery).
- On-policy conversational eval with simulator that has partial expected-result access; end_conversation tool terminates.
- Score = milestone similarity × I(minefield==0); efficiency tracked separately.

## NALLY mapping (Phase 0 audit facts)

- `tests/harness_eval/runner.py`: heuristic intent-accuracy only — **does not meet** ToolSandbox criteria (audit §12). `tests/benchmark/` (cases, judges, runner, reporter, cost tracking) exists but unvalidated as stateful suite.
- `nally/tools/registry.py` + `result.py` + `task_state.py`: structured execution boundary + success detector — the natural Milestone evidence source alongside `receipts.py` JSONL.
- `nally/core/tracing.py`: nested spans + run trees — the trajectory record for milestone matching (turn ↔ milestone topological mapping).
- `nally/agent/graph.py`: parallel tool executor exists — ToolSandbox predicts a race/dependency penalty is needed (larger models parallelize dependent calls and fail).
- `nally/tools/filter.py` augmentations parallel: paper's distraction/name/description scrambling maps directly to testing whether NALLY relies on tool names vs descriptions — and whether `filter.py` keyword matching collapses under scrambling.
- Gap: no Message-Bus equivalent (User/Agent/Environment views), no simulator, no milestone/minefield DAG, no insufficient-info minefields. `permissions.py` headless auto-approve is a safety confound for stateful tests.

## Falsifiable hypothesis

- **H6 (evaluation):** A ToolSandbox-like suite for NALLY (~20 stateful tasks: search→fetch→write→verify with world-state dependencies, multi-turn ambiguity, canonicalization, and deliberately unsolvable tasks with minefields) discriminates architectures that `harness_eval` intent-accuracy cannot — i.e., systems tied on intent-accuracy separate by ≥10pp on milestone score, especially on dependency + insufficient-info categories.
- **H6b (parallelism):** Penalizing parallel calls on dependent tools (or serializing them in `graph.py` executor) improves state-dependency scores vs unconstrained parallel execution.

## Measurable DV (where logged) + Phase 4 ablation

- DV: milestone similarity (intermediate + final), minefield violation rate (hallucinated calls/args when unsolvable), turn count, tool F1, per-category breakdown (STC/MTC/SUT/MUT/SD/C/II), simulator error rate.
- Phase 3 build (not Phase 4): `tests/eval/` with Execution-Context-like world snapshots (file-state checkpoints + project snapshots already in `graph.py`), role-separated message log, milestone/minefield DAGs, on-policy simulator (or scripted multi-turn user as v1). Phase 4 then runs Ablations A–E on this suite.

## Expected counter-evidence (what refutes H6 here)

- If milestone scores rank systems identically to `harness_eval` accuracy (rank correlation ≈1) across ablations, H6 refuted — the heavier suite adds cost without discrimination; keep lightweight eval.
- If state-dependency tasks are solved equally with parallel execution (no race failures observed in NALLY executor), H6b fails here — NALLY tools are less coupled than ToolSandbox's cellular/battery chains.
- If simulator-based conversational scores prove unstable across runs (high variance / simulator hallucinations dominate), on-policy simulation is not yet trustworthy for gating design decisions — fall back to scripted multi-turn users + final-state checks.

## Provider note (OpenCode/hy3-free vs Groq/Llama 3.3)

- Paper shows model-family effects (parallel-call tendency, canonicalization style, memorized vs tool-using behavior) differ by model, not just size. Expect Llama 3.3 vs hy3-free to diverge on SD/C/II categories. Report per-provider category profiles; do not average away the difference.

## Verdict

Not a design decision until built and run. Paper justifies **building the stateful/conversational/interactive harness with milestones + minefields** as Phase 3's measurement foundation — it does not justify any NALLY threshold, parallelism default, or filter choice.
