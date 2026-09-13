# 02 — Experiment Design: H1–H10 Registry + Phase 3 Harness Spec (Phase 2)

Branch: `refactor/nally-architecture-consolidation` · Status: **design-only — no runtime changes**
Phase 1 closed: `docs/research/01-literature-synthesis.md` + `papers/01–10.md`. Invalidation register intact.
This document specifies **what will be run**, on **what harness**, with **what stop rules and interpretation** — it changes no production code, prompt, routing, filter, or permission.

## 0. Global Rules (locked)

1. **Competing hypotheses preserved.** Every experiment has ≥2 arms; no arm is labeled "preferred" in the runner. Interpretation rules decide, not prior belief.
2. **Provider as factor, not assumption.** Every model-sensitive ablation runs on **both** `opencode/hy3-free` and `groq/llama-3.3` and reports per-provider profiles. A claim is "established" only if it replicates on both, or is explicitly scoped ("holds on Groq only").
3. **Measure with existing probes.** Logging = `nally/core/tracing.py` spans + run trees, `nally/tools/receipts.py` JSONL, `nally/agent/verifier.py` verdicts, `nally/tools/registry.py:execute_result` success detector, `nally/agent/context.py` token-usage tracking, `HARNESS_LOG_CLASSIFICATIONS` output. No new instrumentation to make an experiment convenient; Phase 3 harness may add *test-side* scorers (validators, milestone matchers) but not agent-side probes.
4. **Fixed-budget fairness.** Within an ablation, all arms share the same caps: `MAX_TOOL_CALLS=50`, `MAX_ITERATIONS_PER_TURN=30`, `MAX_AGENT_WALL_TIME=300`, `RECURSION_LIMIT=50`, `MAX_TOOL_FAILURES_PER_TURN=5`, `TOOL_RETRY_LIMIT=3`. Planning arms additionally share `PLAN_MAX_STEPS=10`, `PLAN_MAX_REVISIONS=3`, `PLAN_STEP_TIMEOUT=300`, `PLAN_STEP_MAX_ITERATIONS=15`. Thinking arms share `THINKING_MAX_STRATEGIES=3`, `THINKING_TIMEOUT=30`. Deviations are separate IVs, not silent tweaks.
5. **Out of scope (separate track).** `run_command` memory behavior (uncapped foreground `subprocess.run(..., capture_output=True)`) is an **independent engineering/forensic issue**. It is not an IV, DV, or explanation in any H1–H10 experiment. Stateful tests that invoke shell commands must use output caps at the *test-harness level* (truncate-and-record) and must not touch production `system.py`.
6. **Safety freeze.** `nally/config/permissions.json` and headless auto-approve behavior are **observed, not altered** in Phase 4. Stateful suites run sandboxed; `ask` rate is a DV, never tuned mid-experiment.

## 1. Phase 3 Harness Spec (build BEFORE Phase 4 tuning)

`tests/harness_eval/runner.py` (heuristic intent accuracy) stays as-is; it is not the gate. Build `tests/eval/` with four suites below. All suites log trajectories as (`tracing.py` run tree + `receipts.py` entries + role-separated message log) so milestone/validator matching is post-hoc and auditable.

### Suite T (ToolSandbox-like, stateful/conversational/interactive) — primary harness for H1/H2/H3/H5/H10

- **N = 24 tasks**, categories: single-tool (4), multi-tool-chain (4), multi-turn ambiguous start (4), state-dependency incl. 2 nested (5: e.g., send-message→cellular→battery analogues in file/settings domain), canonicalization with/without tool (4: units, currency, relative dates), insufficient-information with minefields (3: task unsolvable — must not hallucinate calls).
- Each task defines: initial world snapshot (files/settings/DB-seed via existing file-checkpoint + project-snapshot machinery, test-side only), available tool allowlist, **milestone DAG** (must-happen: tool-call AST match + world-state exact/loose match, topological order) and **minefields** (must-NOT-happen; violation zeroes the task score), scripted multi-turn user (v1; simulator LLM only in v2 if variance proves acceptable).
- Scoring per task: `score = milestone_similarity × I(minefield==0)` + turn count + tool F1. Suite score = mean + per-category means (STC/MTC/SUT/MUT/SD/C/II).
- Discrimination gate (H6): suite passes if it separates systems tied on `harness_eval` by ≥10pp on milestone mean in pilot (else revise tasks before Phase 4).

### Suite A (AgentBench-like, multi-env interactive) — harness for H7 + routing

- **N = 18 tasks** across 6 envs × 3 each: sandboxed shell (file/dir ops with checking-pipeline verdict), memory-DB query (select/insert/update with hash compare), multi-hop lookup (≥5 tool calls, F1/EM), file-op household (multi-step explore, success/fail), search→choose→verify shopping analogue, web-fetch QA with noise.
- Validity enforcement: unparseable/inexecutable actions, format failures, 3×-identical-output repetition → task fail. Metrics: per-env success, valid-action rate, turns-to-success, repetition-fail rate, per-`harness.py`-class split.

### Suite P (PlanBench-like, mechanical planning) — harness for H4/H9

- **N = 20 tasks**: file-system Blocksworld analogues (stack/move with preconditions), each with lifted-domain description in prompt; tasks: generation (8), cost-optimal (3, action costs stated), verification (3, judge given plan: executable? goal-reaching? first failure + missing precondition/goal), execution-prediction (2), replanning after injected state change (2), reuse/generalization (2). Include **obfuscated variants** (random-name actions/predicates, planner-identical) for ≥6 generation tasks to test retrieval-vs-planning.
- Validator (test-side, PDDL-style or executable checker): executability + goal achievement + optimality gap. Unparseable plan = wrong. Fluency never scored (H4b).

### Suite C (SWE-bench-like, scoped coding) — harness for H8

- **N = 12 tasks**: real issues in this repo or fixtures, each with fail-to-pass + pass-to-pass tests run containerized/sandboxed; gold patch touches 1–3 files. Metrics: resolve rate, apply rate (patch parses/applies — reported separately), localization overlap (files/funcs), patch-size-vs-gold, context tokens/task.
- Retrieval conditions are IVs (see E-H8), not harness defaults.

## 2. Experiment Registry (H1–H10)

Conventions: **IV** = manipulated (env-var/config or test-side condition); **DV** = measured (probe in parentheses); **Control** = baseline arm(s); **n** = tasks × providers; **Stop/abort** = when a run/task halts; **Interpretation** = numeric rule mapping results to re-established / refuted / inconclusive (CIs by bootstrap over tasks; pilot n below, confirm with full n in Phase 4).

### E-H1 — Agent loop (ReAct interleaving)

- **IV:** loop policy: (a) Act-only (thoughts stripped, same trajectories), (b) ReAct-sparse (model-decided thoughts), (c) ReAct-dense (thought each step), (d) ReAct→direct fallback (fail within 7 steps → direct answer).
- **DV:** task success + hallucination rate (`verifier.py` supported/contradicted/fabricated) + iterations/tool-calls/wall-time (`tracing.py`, `receipts.py`) + loop-error rate (repeat thought/action cycles from traces).
- **Control/baseline:** (a) Act-only is the control; pairwise vs (b)/(c); (d) vs best of (a–c).
- **Harness / n:** Suite T multi-step subset (12 tasks) + Suite A household (3) = 15 tasks × 2 providers = 30 runs per arm.
- **Stop/abort:** per-task: success, `MAX_TOOL_FAILURES_PER_TURN=5`, iteration/wall caps, or completion-gate TASK NOT COMPLETE. Abort arm early only for safety faults, never for losing.
- **Logging:** `tracing.py` spans, `receipts.py` JSONL, `verifier.py` verdicts.
- **Interpretation:** H1 re-established if (b) or (c) beats (a) by ≥5pp success AND lower/equal hallucination rate on both providers. Refuted if (a) within ±2pp of best ReAct on milestone success at lower cost. H1b established if (d) beats best single by ≥3pp. Else inconclusive → keep loop as-is, revisit gating.

### E-H2 — Tool selection (PRIORITY; 3 arms + stress)

- **IV:** exposure policy: (a) current `filter.py` (core always-on, weak-cap, strong-match), (b) no-filter full `registry.py`, (c) usefulness-gated hybrid (test-side gate: expose full schemas but instruct call-only-on-expected-gain; no prod filter change). Stress factor (crossed): clean vs distracted/scrambled schemas (3 distraction tools; name/desc/arg-desc scrambling per ToolSandbox A.2.1).
- **DV:** tool precision/recall/F1 (vs milestone gold calls; success from `execute_result` detector + `receipts.py`), task milestone success, prompt tokens/call (`context.py` usage), `ask` rate.
- **Control/baseline:** (a) deterministic filter is the control.
- **Harness / n:** Suite T chain + dependency + canonicalization subset (14 tasks) × clean/stress (2) × 2 providers = 56 runs per arm.
- **Stop/abort:** standard caps; abort task on minefield violation (score 0, still log).
- **Logging:** `receipts.py`, `tracing.py`, `context.py` token counts, permission decisions.
- **Interpretation:** H2 established if (b) beats (a) by ≥5pp F1 AND ≥3pp milestone success on both providers despite higher tokens. Hybrid (c) adopted only if it matches (b)'s success with ≤(a)'s token cost ±10%. Refuted if (a) ≥ (b) on F1 or (b)'s gains appear only single-tool but vanish on chained tasks (Toolformer ≤1-call limit transfers). Scrambling collapse of (a) with (b) holding strengthens H2 independent of clean deltas.

### E-H3 — Context architecture (PRIORITY; placement × budget)

- **IV (two factors, fully crossed):** placement (A current 8-stage; B retrieved+memory-first after system; C retrieved-last before query/call; D query-repeated-both-ends + reranked-first) × budget (memory cap `MAX_MEMORIES_TO_INJECT` ∈ {4, 12}, retrieved-doc budget ∈ {10, 20, 30}, truncation {truncate-oldest-assistant/tool (current) vs rerank-truncate-lowest-relevance}). Plus rerank-vs-stuff arm (top-20 reranked vs all-30 stuffed). Implemented test-side via harness-controlled context assembly; no prod `core.py`/`context.py` change.
- **DV:** task success + best–worst U-gap across gold-position rotations + gold recall (cited/used?) + tokens/latency + prune-drop rate (`context.py` tracking).
- **Control/baseline:** (A, 12, 20, current-truncation) is the control = today's architecture.
- **Harness / n:** Suite T QA/lookup + dependency tasks with rotatable gold position (12 tasks × 3 gold positions) + Suite A lookup env (3) = 15 task-forms × 4 placements × 3 budgets (10/20/30 with memory 12; plus memory-4 spot-check on winner) × 2 providers. Run in two waves: wave 1 placements × 20-docs (cheapest screen), wave 2 winner × budgets + rerank arm.
- **Stop/abort:** standard caps; abort placement arm only on systematic format collapse (>30% unparseable), still report.
- **Logging:** `context.py` usage, `tracing.py`, gold-position manifest (test-side), `receipts.py`.
- **Interpretation:** H3 established if any non-A placement beats A by ≥5pp success with smaller/equal U-gap on both providers. Saturation established if 20→30 adds <1.5pp (paper's number as threshold) while tokens/latency rise >25%. H3b established if D beats C by ≥3pp on stateful tasks (key-value-only win doesn't count). All-within-±2pp → refuted; lever is retrieval quality/budget, not order.

### E-H4 — Planning gate (PRIORITY; three separable factors)

- **IV (factorial, not one knob):** F1 `PLAN_ENABLED` {true, false} × F2 `task_router.py` promotion {on (ReAct→PLAN allowed), off (forced REACT)} × F3 uncertainty gate {off, on (PLAN only when harness confidence low OR multi-dependency detected; AMBIGUOUS low-conf → clarifying-question per UoT-lite, capped 1 question)}. `PLAN_MAX_STEPS/REVISIONS` fixed; `human_checkpoint.py` on for HIGH_STAKES/CREATIVE in all arms (catch rate measured, policy frozen).
- **DV:** plan validity (validator: executable + achieves goal) + optimality gap + replan success + checkpoint/verifier catch rates + tokens/wall-time + per-class split.
- **Control/baseline:** today's cell (true × on × off) is the control.
- **Harness / n:** Suite P full (20, incl. obfuscated) + Suite T chains (6) = 26 tasks × key cells (minimum 4: control, false×off×off, true×on×on-gated, true×off×on-gated to isolate F1/F2/F3) × 2 providers = 52 runs per reported cell; full 2×2×2 only if pilot shows interaction.
- **Stop/abort:** plan validator fail = task fail (log fluency separately for H4b contrast); replan tasks inject one state change mid-execution; human-checkpoint timeout = fail-closed (counted, not retried).
- **Logging:** validator verdicts (test-side), `tracing.py`, `human_checkpoint.py` events, `verifier.py`.
- **Interpretation:** H4 established if gated cell beats control by ≥5pp validity at ≤ control cost on both providers. H4b established if fluency-ranked winner ≠ validator-ranked winner on ≥20% of tasks (fluent-but-invalid common). Refuted if control wins on validity×cost → keep `PLAN_ENABLED=true`, tune steps/revisions instead. Obfuscated ≈ clean → retrieval-vs-planning moot for these domains.

### E-H5 — Reflection + memory

- **IV:** retry policy {blind-retry, failure-gated-reflection (trigger: repeat-cycle>Ω OR consecutive-error breaker OR verifier contradicted/fabricated → 1 verbal reflection → episodic write → 1 retry), reflect-always} × background {hourly `reflector.py` on/off} × decay {bucketed (current 1.0/0.9/0.7/0.5/0.3) vs flat 1.0}. Reflection prompt frozen; reflector model = same (heterogeneous-model variant only if same-model fails).
- **DV:** trial-1→trial-2 success delta (learning curve) + loop rate + steps-to-success + tokens/trials cost + reflection helpfulness (trial-2 avoided named mistake? judge test-side).
- **Control/baseline:** blind-retry (1 retry, no reflection) is the control. Include WebShop-like tool-quality-bound task (2 tasks) as negative control where ~0 lift is the *correct* outcome.
- **Harness / n:** Suite T recoverable-failure subset (10: loops, wrong-search reformulable) + 2 bottleneck controls = 12 × 2 providers per retry-policy; background/decay factors run on recoverable subset only.
- **Stop/abort:** max 2 trials (1 retry) per task; stop on success or no-improvement; never exceed 3 stored reflections (paper cap).
- **Logging:** `tracing.py` (cycle detection), `receipts.py`, `verifier.py`, memory writes (store API logs test-side), `reflector.py` run markers.
- **Interpretation:** H5 established if gated-reflection beats blind by ≥8pp trial-2 delta with loop-rate drop on both providers. H5b established if hourly-off preserves ≥80% of the gated lift (batch not the ingredient). Refuted if gated ≈ blind ±2pp at higher cost → failures are tool/context-bound; keep current schedule, skip per-failure machinery.

### E-H9 — Deliberate search (ToT) + L2M ordering

- **IV:** reasoning policy {linear (current ReAct/CoT), fan-out (current ThinkTool k=3, no vote), ToT-BFS (k=3 candidates, vote, b=2, depth≤3), ToT-DFS (k=3, value-threshold prune + backtrack, ≤20 steps)} × task type {pivotal-early-decision (step-1 conditions chain) vs routine}. L2M-ordering {flat plan order vs easy-verifiable-first with answer injection} crossed on compositional subset.
- **DV:** success + cost (tokens, LLM calls, wall time) + backtrack rate + prune precision + best-state-vs-output gap (oracle check test-side).
- **Control/baseline:** linear is the control; routine tasks are the "should-tie-or-lose" control for cost.
- **Harness / n:** Suite P generation/replan (8 hard) + Suite T pivotal chains (4) + routine controls (6: SIMPLE/KNOWLEDGE) = 18 × 2 providers per policy.
- **Stop/abort:** depth/step caps above; prune kills subtree (logged); backtrack to parent; cost circuit-breaker: abort ToT arm task at 10× linear tokens (count as fail, report cost).
- **Logging:** `tracing.py` (branch/prune/backtrack markers test-side), `thinking` engine outputs, validator/milestone verdicts.
- **Interpretation:** H9 established if ToT beats linear by ≥8pp on pivotal tasks on both providers *and* ties (±2pp) or loses cost-adjusted on routine (justifying a gate). Refuted if ≤±2pp at ≥3× cost, or value/vote ≈ chance (prune kills good branches / best-state ≫ output). H9b established if L2M order beats flat by ≥5pp on compositional subset.

### E-H10 — Verification/sampling + uncertainty ask-gate

- **IV:** judging {single-path, single+`verifier.py` (current), SC-3, SC-5 (temperature fixed per provider, plurality vote)} × task split {fixed-answer reasoning (no receipts) vs tool-grounded (receipts exist)}; ask-gate {off vs UoT-lite on AMBIGUOUS (1 candidate-clarification simulation, max-information-gain ask, then act)}.
- **DV:** accuracy/success + consistency% (agreement rate → calibration curve) + verifier catch rate + questions-to-success + tokens/calls + human-review rate.
- **Control/baseline:** single+verifier is the control (the cheap baseline sampling must beat).
- **Harness / n:** reasoning split (8: Suite A lookup + Suite P verification/execution) + grounded split (8: Suite T chains) + AMBIGUOUS ask-gate (6: Suite T multi-turn) = 22 × 2 providers per judging arm (SC arms only on reasoning + grounded; ask-gate only on AMBIGUOUS).
- **Stop/abort:** SC temperature/seed fixed and pre-registered; ties → first-encountered (paper rule); ask-gate max 1 question then must act.
- **Logging:** `verifier.py` verdicts, vote tallies + consistency% (test-side scorer), `human_checkpoint.py` events, `tracing.py`.
- **Interpretation:** H10 established if SC-3/5 beats control by ≥5pp on reasoning-no-receipt *and* ties (±2pp) on grounded (justifying gating, not always-on). Calibration established if low-consistency predicts failure (top-tercile consistency ≥15pp more accurate than bottom). Refuted if SC ≤+2pp everywhere → keep receipt-verifier, drop sampling. H10b established if ask-gate beats direct by ≥5pp success-per-cost on AMBIGUOUS.

### E-H6/H7/H8 — Evaluation-build acceptance (not architecture claims)

- **H6:** Suite T pilot (run 2 reference configs: e.g., filter-on vs filter-off) must show ≥10pp milestone separation while `harness_eval` accuracy ties (±3pp) → suite discriminates; else revise tasks. Minefield check: deliberately hallucinating agent must score 0 on II tasks.
- **H7:** Suite A pilot must show class ordering + valid-action-rate variance explained (report R²-style decomposition; interpretation: validity vs plan-quality attribution, no threshold — descriptive).
- **H8:** Suite C pilot: tight-hunk vs full-file vs BM25-stuffed × single vs test-feedback-loop; H8 established if loop+tight beats single-shot by ≥10pp resolve rate and stuffed-context curve is non-monotonic (length-degradation). Report resolve AND apply separately (format vs reasoning confound, provider-sensitive).

## 3. Run Order + Budget

1. Build Phase 3 suites (T → P → A → C) with pilots + discrimination checks. No Phase 4 arm starts on an unvalidated suite.
2. Wave 1 (cheapest screens, both providers): E-H3 placements@20docs; E-H2 clean-only 3 arms; E-H4 4 key cells; E-H10 single vs +verifier vs SC-3 (reasoning split only).
3. Wave 2 (winners + stress): E-H3 budgets + rerank; E-H2 stress crossing; E-H4 full factorial only if interaction signal; E-H1, E-H5, E-H9, E-H8 full.
4. Estimated runs: T(24)+A(18)+P(20)+C(12)=74 task-forms; × positions/variants ≈ 110; × arms (avg 3) × providers (2) ≈ 500–700 Phase 4 runs + pilots. Cap: 700. If budget binds, cut in order: H9 full-factorial → H9 pivotal-only; H5 decay factor → deferred; never cut both-provider replication on P1 (H2/H3/H4).

## 4. Reporting (Phase 4 output contract → `docs/research/04-results.md`)

Per Hn: table (arm × provider: DV mean + 95% CI + cost) + interpretation verdict (**re-established / refuted / inconclusive**) + invalidation-register row update. Priority verdicts (H2/H3/H4) each get success×cost Pareto + per-provider profile. Raw logs stay out of git (separate data dir); narrative + tables git-tracked here. No architecture change ships without an `H→experiment→result` link recorded in `05-architecture.md`.
