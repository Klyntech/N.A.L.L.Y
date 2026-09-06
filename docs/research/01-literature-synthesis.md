# 01 — Literature Synthesis: From Papers to Falsifiable NALLY Hypotheses (Phase 1)

Branch: `refactor/nally-architecture-consolidation` · Output: `docs/research/` (git-tracked) · Status: **read-only synthesis — no design decisions**
Rule enforced: **a paper result that sounds applicable is not a design decision.** Each claim below becomes an `Hn` with a DV and a Phase 4 ablation; it must survive the repo's actual architecture and measurement.

## 1. Master Table

| Paper | NALLY Dimension | Hypothesis | Priority | Measurable DV (probe) | Phase 4 Ablation |
|---|---|---|---|---|---|
| 01 ReAct (ICLR23) | Agent loop | H1: in-loop Thought-Act-Obs beats Act-only and detached ThinkTool on COMPLEX/multi-step; H1b: ReAct→direct fallback beats either alone | P1-adjacent | success, hallucination rate (`verifier.py`), iterations/calls/wall time (`tracing.py`, `receipts.py`), loop-error rate | A: Act-stripped vs ReAct-sparse vs dense vs fallback |
| 02 Toolformer (2023) | Tool selection | H2: LLM self-selects from full `registry.py` beats `filter.py` deterministic core/weak-cap on F1/success; H2b: usefulness-gated trigger beats forced triggers | **P1** | tool P/R/F1, milestone success, tokens/call, `ask` rate | C: no-filter vs current-filter vs usefulness-gated |
| 03 Lost in the Middle (2023) | Context architecture | H3: placement at beginning/end beats middle-burial; gains saturate ~20 docs; H3b: query-before+after helps | **P1** | success, best-worst U-gap, gold recall, tokens/latency, prune-drop rate | A: ≥4 order permutations × budgets + rerank/truncate |
| 04 PlanBench (NeurIPS23 DB) | Planning eval + gate | H4: uncertainty-gated PLAN beats always-on `PLAN_ENABLED=true` on success/cost; H4b: validator scoring reverses fluency wins | **P1** | validity, optimality gap, replan success, catch rate, cost, per-class split | B: PLAN on/off/uncertainty-gated × promotion on/off |
| 05 Reflexion (2023) | Memory/reflection | H5: failure-triggered verbal reflection + one retry beats blind retry; H5b: trial-gated drives gain, not hourly batch | P2 | trial1→2 delta, loop rate, steps-to-success, cost | E: blind vs gated-reflection vs always × hourly on/off × decay flat/bucketed |
| 06 ToolSandbox (2024) | Tool-use eval | H6: stateful milestone/minefield suite discriminates where `harness_eval` cannot (≥10pp splits); H6b: dependency-aware serialization wins | Eval foundation | milestone similarity, minefield violations, turns, per-category (SD/C/II) | Phase 3 build; then run A–E on it |
| 07 AgentBench (2023) | Overall agent eval | H7: COMPLEX→AMBIGUOUS gap largest; validity explains variance; H7b: LLM-classifier routing beats regex-fallback | Eval foundation | per-env success, valid-action rate, turns, repetition-fails | Routing: LLM vs regex vs none on AgentBench-like suite |
| 08 SWE-bench (2023) | Coding-agent eval | H8: localize→edit→test loop with tight hunks beats single-shot/BM25-stuffing; performance drops as stuffed context grows | Eval foundation | resolve/apply rates, localization overlap, patch size, tokens | Tight-hunk vs full-file vs BM25 × single vs loop |
| 09 Tree of Thoughts (NeurIPS23) | Planning/search | H9: gated ToT (k≥3, value/vote, backtrack) wins only on pivotal-early-decision tasks at 3–10× cost; H9b: L2M ordering wins on compositional tasks | P2 | success, cost, backtrack/prune stats, best-state gap | D2: linear vs fan-out vs BFS vs DFS on hard + routine controls |
| 10 Self-Consistency + CoT/L2M/UoT | Verification/judging | H10: SC-3/5 wins on fixed-answer reasoning, ties receipt-check on tool-grounded → gate it; H10b: UoT-lite ask-gate wins on AMBIGUOUS | P2 | accuracy, consistency% calibration, verifier catch rate, questions-to-success, cost | D: single vs +verifier vs SC-3/5 × splits; UoT-lite vs direct vs PLAN |

Supporting roles: CoT = elicitation baseline for H1/H9/H10; Least-to-Most = decomposition ordering for H4/H9; Uncertainty of Thoughts = commit-vs-gather gate for H4/H10 (candidate simulation + information-gain reward + max-Re selection).

## 2. Priority Deep-Dives

### P1-1: Context Architecture (H3) — decide first, everything else sits inside it

Current architecture (audit): `core.py` 8-stage assembly with memory@idx1, summary@idx1, auto-websearch, scratchpad, re-prune, tool-surface selection, then `graph.py` receipt-as-system before `llm_call`; `context.py` preserves user/system while dropping old assistant/tool; `platform.py` adds OS/shell bulk.

What literature demands: test `system + memory + tools + conversation + retrieved` as **placement × budget**, not one prompt doc. Minimum matrix: (A) current; (B) retrieved+memory-first; (C) retrieved-last-before-query; (D) query-repeated-both-ends + reranked-first — each × 10/20/30-doc budgets, plus a rerank/truncate arm (paper §5). Query-aware (H3b) gets its own arm because the paper's key-value fix did not transfer to QA — NALLY must check both QA-like and stateful tasks.

Decision sketch (to validate, not to adopt):
```
need mid-context fact?
 ├─ rerank: is gold in top-k? ── no ──▶ truncate to k (don't stuff)
 └─ place: gold at very-start (after system) or very-end (before query/call)?
     └─ query repeated before block AND at end? (H3b arm)
```

### P1-2: Tool Selection (H2) — the direct challenger to current `filter.py`

Current: deterministic keyword preselection (core always-on; strong-match exposes; weak capped; none→core). Toolformer predicts model-decided selection wins on F1, especially chained tasks — but warns single-call limits and context costs.

Competing hypotheses required by acceptance criteria: (i) keep `filter.py` (precision/budget wins); (ii) remove it (recall/F1 wins); (iii) usefulness-gated hybrid (precision without recall loss). ToolSandbox augmentations (distraction/scrambled names/descriptions) become the stress test: if `filter.py` keyword matching collapses under scrambling while LLM selection holds, H2 strengthens regardless of clean-task deltas. Provider split mandatory: function-call fidelity differs (native vs XML-like fallback), so run Ablation C on both providers.

### P1-3: Planning Gate (H4) — `PLAN_ENABLED=true` is on trial

Current: planning defaults enabled; `task_router.py` promotes some ReAct→PLAN; `human_checkpoint.py` gates COMPLEX/HIGH_STAKES/CREATIVE with fail-closed timeout; no validator. PlanBench + UoT jointly predict: mechanical validity (not fluency) is the metric, and an uncertainty gate (PLAN only when harness confidence low or multi-dependency detected; else REACT/DIRECT; ask clarifying question when information gain high) beats always-on.

Decision sketch (to validate):
```
harness class + confidence?
 ├─ SIMPLE/KNOWLEDGE high-conf ──▶ DIRECT/REACT (no plan)
 ├─ COMPLEX + dependencies ──▶ PLAN (validator-scored)
 ├─ AMBIGUOUS low-conf ──▶ UoT-lite: simulate candidates → max information-gain ask/act
 └─ HIGH_STAKES ──▶ PLAN + human_checkpoint (measure catch rate)
```
Obfuscated (random-name) variants test retrieval-vs-planning; fluency-vs-validity split (H4b) prevents false wins.

## 3. P2 Dimensions (still required, deferred cost)

- **Agent loop (H1):** ReAct interleaving vs Act-only vs detached ThinkTool; ReAct→direct fallback. Gated by H3 (loop lives inside context) and H4 (loop vs plan).
- **Reflection (H5):** failure-gated verbal retry with episodic memory; hourly batch vs trial-gated; decay flat vs bucketed. Includes the WebShop negative control (tool-quality-bound tasks where reflection correctly shows ~0 lift).
- **Search (H9):** ToT-BFS/DFS with value/vote + backtrack, gated to pivotal-decision hard subsets; L2M ordering. Heterogeneous provider mapping allowed (strong evaluator + cheap generator).
- **Verification (H10):** SC-3/5 + consistency calibration + UoT-lite ask-gate vs cheap single+`verifier.py` receipt baseline. Sampling never always-on.

## 4. Evaluation Foundations (build before tuning — Phase 3)

- **ToolSandbox-like (`tests/eval/`):** Execution-Context snapshots (reuse file checkpoints + project snapshots), role-separated log, milestone/minefield DAGs, on-policy simulator (scripted users as v1), categories STC/MTC/SUT/MUT/SD/C/II, race penalty for parallel-on-dependent calls, turn-count efficiency.
- **AgentBench-like:** 5–6 envs (sandboxed OS commands with checking pipeline, DB-style memory queries with hash checks, KG-style multi-hop, file-op household, search→choose→verify shopping) with validity enforcement.
- **PlanBench-like:** file-system planning with planner+validator, obfuscated variants, 8-task curriculum adapted (generation, optimal, verification, execution, reformulation, reuse, replan, generalization).
- **SWE-bench-like (`tests/eval/coding/`):** real issues + fail-to-pass/regression containers, resolve/apply/localization metrics, retrieval ablations.
CI (`lint` + `pytest`) stays green; `harness_eval` remains but is not the gate.

## 5. Traceability Matrix (H → audit → file → ablation)

| H | Audit § | Files | Ablation |
|---|---|---|---|
| H1 | loop, thinking | `agent/graph.py`, `agent/core.py`, `thinking/engine.py`, `thinking/tool.py` | A |
| H2 | tool surface | `tools/registry.py`, `tools/filter.py`, `tools/permissions.py`, `config/permissions.json` | C |
| H3 | context arch | `agent/core.py`, `agent/context.py`, `agent/platform.py`, `memory/store.py`, `agent/graph.py` (receipts) | A (context matrix) |
| H4 | planning, routing | `agent/planner.py`, `agent/task_router.py`, `agent/harness.py`, `agent/human_checkpoint.py` | B |
| H5 | memory | `memory/reflector.py`, `memory/store.py`, `memory/confidence.py`, `memory/models.py`, `agent/scratchpad.py` | E |
| H6 | eval/tests | `tests/harness_eval/runner.py`, `tests/benchmark/`, `tools/receipts.py`, `tools/result.py`, `core/tracing.py` | Phase 3 build |
| H7 | routing/eval | `agent/harness.py`, `agent/scratchpad.py`, `agent/sessions.py`, `engineering/` | Routing ablation |
| H8 | coding eval | `engineering/`, `tools/code.py`, `tools/files.py`, `tools/system.py`, `agent/graph.py` snapshots | Coding ablation |
| H9 | thinking/planning | `thinking/engine.py`, `thinking/strategies.py`, `thinking/prompts.py`, `agent/planner.py` | D2 |
| H10 | verification | `agent/verifier.py`, `tools/receipts.py`, `agent/human_checkpoint.py`, `thinking/tool.py` | D |

## 6. Not Design Decisions Yet (invalidation register — Phase 0 + locked)

- No minimal core-prompt token count; no context ordering claimed superior (H3 matrix undecided).
- No `filter.py` threshold as optimal (H2 A/B required).
- No approval-unity optimality (headless auto-approve measured later, not blessed).
- No planning default (`PLAN_ENABLED=true` under test in H4; promotion rule unvalidated).
- No sampling/judging benefit (H10 gated test required).
- No reflection/decay optimality (H5 schedule test required).
- No provider-general claim (every model-sensitive H runs both OpenCode/hy3-free and Groq/Llama 3.3).

## 7. Phase 2 Handoff (experiment design inputs)

For each Hn, Phase 2 must specify IV/DV/harness/abort: IV from config knobs (`MAX_MEMORIES_INJECTED`, `CONTEXT_COMPRESSION_THRESHOLD`, `NALLY_MAX_TOOL_CALLS/ITERATIONS/OUTPUT/WALL_TIME`, `RECURSION_LIMIT`, `PLAN_MAX_STEPS/REVISIONS`, `THINKING_MAX_STRATEGIES/TIMEOUT`, `APPROVAL_TIMEOUT`); DV from probes above; harness from §4 suites; abort mirroring `human_checkpoint.py` fail-closed semantics. Raw experimental data lives outside `docs/research/`; narrative + tables stay git-tracked here.
