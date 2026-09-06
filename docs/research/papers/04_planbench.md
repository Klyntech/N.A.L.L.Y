# 04 — PlanBench: An Extensible Benchmark for Evaluating LLMs on Planning (Valmeekam et al., NeurIPS 2023 DB) — PRIORITY 3

Source: https://arxiv.org/abs/2206.10498 (v4; HTML v4 inspected, §§1,4–7)

## Finding (1–2 sentences)

Planning must be evaluated *mechanically* (planner + validator on PDDL IPC domains), not via fluent prose: even SOTA LLMs fail frequently at plan generation, cost-optimal planning, verification, execution reasoning, replanning, reuse, and generalization — with obfuscation (misleading/random names) exposing retrieval-vs-planning.

## Evidence strength

- Curriculum (8 tasks): plan generation, cost-optimal, verification, execution reasoning, goal-reformulation robustness, reuse, replanning, generalization; domains Blocksworld (600 instances) + Logistics (285) + obfuscated variants; ~26,250 prompts; template PDDL↔NL translator; validator-checked outputs (plan-end tag; unparseable = wrong).
- Specimen (Blocksworld): GPT-4 — generation 206/600 (34.3%), optimal 198/600 (33%), verification 352/600 (58.6%), execution 191/600 (31.8%), replanning 289/600 (48.1%), generalization 141/500 (28.2%), reuse 392/600 (65.3%), goal-shuffle 461/600 (76.8%), full→partial 522/600 (87%), partial→full 348/600 (58%). InstructGPT-3 far worse (generation 6.8%). Fluency ≠ validity is the core result.
- Architecture: domain-independent (planner, validator, test-case generator) + domain-dependent (lifted model, problem generator, translator) — directly reusable as an eval pattern.
- Strength: large-scale mechanical validation + obfuscation control. Weakness: one-shot NL prompts only in main report (other configs in companion work); Blocksworld/Logistics are toy vs real repo tasks; no cost/latency; absolute numbers prompt- and version-sensitive.

## Assumptions

- Classical goal-directed deterministic planning `P=⟨D,I,G⟩`; lifted domain in prompt constrains actions; few-shot exemplars + new instance; symbolic validator as ground truth.
- Tests retrieval-vs-reasoning via obfuscated names (planner sees identical problem; LLM should not benefit from commonsense labels if truly planning).

## NALLY mapping (Phase 0 audit facts) — highest leverage

- `nally/agent/planner.py`: LangGraph Plan-and-Execute (classify → planner | llm → planner → critique → execute_step → replan → execute_step | planner → synthesize | llm) over **flat ordered steps** with max steps/revisions/per-step iterations/timeout. Audit: `PLAN_ENABLED` defaults to **enabled** on this branch (brief's `false` was stale) — so planning is currently on without mechanical proof it helps.
- `nally/agent/task_router.py`: DIRECT/REACT/PLAN/DELEGATE/ENGINEERING + rule-based ReAct→PLAN promotion; downgrades to REACT when kill-switch off. This promotion rule is precisely what PlanBench says to validate mechanically.
- `nally/agent/human_checkpoint.py`: plan-level review (store plan, emit event, wait approve/edit/reject, fail-closed on timeout) scoped to COMPLEX/HIGH_STAKES/CREATIVE — a verification gate with no measured catch rate.
- `nally/agent/harness.py`: cheap LLM classifier (class/confidence/reasoning JSON) + regex fallback ordered HIGH_STAKES > CREATIVE > KNOWLEDGE > COMPLEX > SIMPLE > AMBIGUOUS; per-class critique/scratchpad/tool-verify stages.
- Gap: `tests/harness_eval/runner.py` is heuristic intent-accuracy only; `tests/benchmark/` exists but is not a PlanBench-style mechanical suite. No validator equivalent for `planner.py` flat steps exists today.

## Falsifiable hypothesis

- **H4 (planning gate, PRIORITY 3):** On this branch, `task_router.py:PLAN` (full Plan-and-Execute) beats `REACT` only on a narrow subset (multi-step with dependencies, low harness confidence); on SIMPLE/KNOWLEDGE/CREATIVE-direct tasks it ties or loses on success per token/latency. An **uncertainty-gated** policy (PLAN only when `harness` confidence low or multi-dependency detected; else REACT/DIRECT) beats always-on `PLAN_ENABLED=true` on aggregate success per cost.
- **H4b (mechanical scoring):** Scoring `planner.py` outputs with a validator (executability + goal achievement + optimality gap) rather than fluency/human rating reverses apparent wins — fluent-but-invalid plans are common, mirroring PlanBench's 34% generation rate.

## Measurable DV (where logged) + Phase 4 ablation

- DV: plan validity (executable + achieves goal, validator-checked), optimality gap, replanning success after injected change, verification catch rate (`human_checkpoint.py` + `verifier.py`), tokens + wall time (`tracing.py`), per-class breakdown by `harness.py` class.
- Ablation B (Phase 4): PLAN-enabled vs disabled vs uncertainty-gated × `task_router` promotion on/off; tasks: Blocksworld-style file-system planning (mechanically verifiable) + NALLY multi-step chains (search→fetch→write→verify); report validity × cost, not fluency. Build Phase 3 PlanBench-like suite first (validator + obfuscated variants to test retrieval-vs-planning).

## Expected counter-evidence (what refutes H4 here)

- If always-on PLAN beats uncertainty-gated REACT on both validity *and* cost across task classes, H4 refuted — keep `PLAN_ENABLED=true` and tune `PLAN_MAX_STEPS`/revisions instead.
- If validator-scored gaps vanish on obfuscated (random-name) variants — i.e., NALLY plans equally well without commonsense labels — the retrieval-vs-planning concern is moot for this repo's domains.
- If `planner.py` flat ordered steps validate at high rates (>80%) on file-system tasks, PlanBench pessimism does not transfer — NALLY's constrained tool domains are easier than IPC reasoning.

## Provider note (OpenCode/hy3-free vs Groq/Llama 3.3)

- PlanBench deltas are SOTA-sensitive (GPT-4 34% vs InstructGPT 6.8%). Llama 3.3 vs hy3-free may straddle a similar capability cliff for multi-step validity. Phase 4 Ablation B must run on **both**; gating thresholds tuned on one provider must re-validate on the other. Supporting `Uncertainty of Thoughts` gating (commit vs gather-info) is explicitly provider-sensitive and belongs in Phase 2 design.

## Verdict

Not a design decision until ablation. Paper justifies building a **mechanical planning benchmark** and testing an uncertainty gate — it does not justify enabling/disabling planning, any step/revision budget, or the current ReAct→PLAN promotion rule.
