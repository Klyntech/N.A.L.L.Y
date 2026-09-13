# 01 — ReAct: Synergizing Reasoning and Acting in Language Models (Yao et al., ICLR 2023)

Source: https://arxiv.org/abs/2210.03629 (v3 camera-ready; HTML v3 inspected)

## Finding (1–2 sentences)

Interleaving verbal reasoning traces (Thought) with environment actions (Act) and observations (Obs) in a single LLM decoding loop outperforms reasoning-only (CoT) and acting-only (Act) baselines: reasoning tracks/updates/repairs plans, while acting grounds the model with external information.

## Evidence strength

- Domains: HotpotQA + FEVER (knowledge-intensive, Wikipedia API with search/lookup/finish) and ALFWorld + WebShop (interactive decision-making).
- Key deltas (PaLM-540B prompting): Fever ReAct 60.9 vs CoT 56.3 vs Act 58.9; HotpotQA ReAct 27.4 vs CoT 29.4 vs Act 25.7; combined ReAct→CoT-SC 35.1 / CoT-SC→ReAct 34.2–64.6 beat either alone. ALFWorld best ReAct 71% vs Act 45% vs BUTLER 37%; WebShop ReAct SR 40.0 vs Act 30.1 vs IL+RL 28.7.
- Human error analysis (n=200 HotpotQA): CoT hallucination as failure mode 56% vs ReAct 0%; ReAct false-positive rate 6% vs CoT 14%; but ReAct reasoning/loop errors 47% vs CoT 16%, non-informative search 23%.
- Finetuning (3k bootstrapped trajectories): PaLM-8B ReAct-finetuned beats all PaLM-62B prompting methods; PaLM-62B ReAct-finetuned beats all 540B prompting methods.
- Strength: strong multi-domain replication with controlled Act ablation (same trajectories minus thoughts) + IM-style ablation (ReAct 71 vs ReAct-IM 53). Weakness: few-shot prompting only (1–6 exemplars), greedy decoding, PaLM-centric; no latency/cost analysis; Wikipedia API deliberately weak (exact-title search).

## Assumptions

- Frozen large LM (PaLM-540B; GPT-3 appendix) with strong in-context priors; dense Thought-Act-Obs for QA, sparse model-decided thoughts for decision tasks.
- Small discrete action space (3 Wikipedia ops; ALFWorld text actions; WebShop search/choose/buy) with textual observations appended verbatim to context.
- Evaluation = EM/accuracy/success rate; no context-placement, tool-count scaling, or provider-variance analysis.

## NALLY mapping (Phase 0 audit facts)

- `nally/agent/graph.py`: LangGraph state-machine already described as ReAct-style (think → tool → observe → continue); `llm_call` node with abort checkpoint, consecutive-error + total-tool-call circuit breakers, receipt injection as system message before generation, native + XML-like tool-call parsing, final-response claim-verification + completion gate (TASK NOT COMPLETE).
- `nally/agent/core.py`: multi-stage context assembly (user msg → guardrails → harness/task_router → scratchpad → skills → pruning/compaction → memory@idx1 → summary@idx1 → websearch → scratchpad → pruning → tool-surface selection → `run_agent`), not a single prompt.
- `nally/agent/harness.py` (6 classes) + `nally/agent/task_router.py` (DIRECT/REACT/PLAN/DELEGATE/ENGINEERING): routing layers that decide *when* ReAct runs vs direct/plan — exactly the "when to think/act" question ReAct leaves open.
- `nally/thinking/tool.py` + `engine.py`: separate multi-call ThinkTool with heuristic strategy selection — ReAct would predict sparse in-loop thoughts beat a detached tool call, untested here.

## Falsifiable hypothesis

- **H1 (agent loop):** For COMPLEX/multi-step tasks on this branch, in-loop interleaved Thought-Act-Obs via `graph.py` achieves higher task success and lower hallucination rate than (a) Act-only (thoughts stripped) and (b) detached ThinkTool-only pre-planning, at the cost of more iterations/tool calls.
- **H1b (combination):** A ReAct→direct fallback (ReAct fails within N steps → back off to direct/CoT-style answer) beats either alone on knowledge tasks, mirroring ReAct→CoT-SC gains.

## Measurable DV (where logged) + Phase 4 ablation

- DV: task success (ToolSandbox-like suite, Phase 3), hallucination rate (`verifier.py` supported/contradicted/fabricated), iterations + tool calls + wall time (`tracing.py` spans, `receipts.py` JSONL), loop-error rate (repetitive thought/action detection from traces).
- Ablation A (Phase 4): Act-stripped vs ReAct-sparse vs ReAct-dense vs ReAct→direct-fallback on same tasks; fixed `NALLY_MAX_ITERATIONS` / `NALLY_MAX_TOOL_CALLS`; report success × cost Pareto.

## Expected counter-evidence (what refutes H1 here)

- If Act-only matches ReAct success within ±2% on stateful multi-turn suite while using fewer tokens/steps, H1 refuted for this repo (reasoning overhead not justified).
- If detached ThinkTool pre-plan matches in-loop thoughts on COMPLEX tasks, ReAct's sparsity claim fails here — architecture should keep thinking outside the loop.
- If ReAct increases loop/repetition failures (paper's 47% reasoning-error pattern) beyond the completion gate's ability to force TASK NOT COMPLETE, the loop as currently guarded is net harmful without better decoding/stop rules.

## Provider note (OpenCode/hy3-free vs Groq/Llama 3.3)

- ReAct relies on instruction-following for Thought/Action formatting (native vs XML-like fallback in `graph.py`). Effect may diverge: weaker function-call fidelity → more parse repairs/retries; longer-context handling → more loop errors. Phase 4 must run Ablation A on **both** providers; do not generalize from one.

## Verdict

Not a design decision until ablation. Paper justifies testing in-loop ReAct vs Act-only vs detached thinking — it does not justify current `graph.py` safeguards, iteration budgets, or routing thresholds.
