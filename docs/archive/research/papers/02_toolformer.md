# 02 — Toolformer: Language Models Can Teach Themselves to Use Tools (Schick et al., 2023)

Source: https://arxiv.org/abs/2302.04761 (v1; HTML v1 inspected, §§1–5)

## Finding (1–2 sentences)

A LM can learn *when* to call which API, *what arguments* to pass, and *how to incorporate results* via self-supervised filtering: sample candidate calls from few-shot prompts, keep only calls where `L⁻ − L⁺ ≥ τf` (result reduces next-token loss), finetune on the augmented corpus. Toolformer (GPT-J 6.7B) then beats much larger models zero-shot without losing base LM ability.

## Evidence strength

- Tools: QA (Atlas), calculator, Wikipedia BM25 search, NLLB translation, calendar; constraint: I/O as text, few demos each.
- Deltas (zero-shot, greedy + top-k API trigger): LAMA SQuAD/Google-RE/T-REx +11.7/+5.2/+18.6 over best GPT-J baseline, beating OPT-66B and GPT-3-175B (tool use 98.1% QA); math ASDiv/SVAMP/MAWPS 40.4/29.4/44.0 vs GPT-3 14.0/10.0/19.8 (calculator 97.9%); QA WebQS/NQ/TriviaQA beats same-size baselines (search 99.3%) but trails GPT-3; temporal Dateset 27.3 vs ≤5.9 (calendar 54.8%); TempLAMA gains came from search/QA not calendar (0.2%).
- No perplexity cost when APIs disabled (WikiText/CCNet).
- Scaling: tool benefit emerges ~775M params; gap with/without tools persists at 6.7B.
- Calibration: at k=1, model calls APIs on examples it would otherwise fail (AC vs NC split); lost at higher k.
- Strength: clean self-supervised criterion + generality preserved. Weakness: single API call per input, no interactive reformulation/browsing (authors flag QA-search shortfall vs GPT-3 for this reason); GPT-J/CCNet-specific; decoding hack (k=10) inflates tool use; threshold τf tuned per tool.

## Assumptions

- Pretrained LM finetuned on its own pretraining distribution augmented with useful calls; API docs = handful of examples; loss-reduction = usefulness proxy.
- Zero-shot evaluation with lenient metrics (first-number / contains-answer); at most one tool call per input.
- No permission/approval, no multi-tool chains, no cost model.

## NALLY mapping (Phase 0 audit facts)

- `nally/tools/registry.py`: canonical registry (name/desc/schema/permission category → OpenAI function schemas); `execute_result` boundary (lookup, plugin fallback, truncation, ToolResult conversion, success detector: empty=success, "Error"=fail, run_command exit-code marker).
- `nally/tools/filter.py`: **deterministic keyword/token preselection** before the model — always-on core set, strong-match exposes all matched, weak-match capped, no-match → core fallback. This is the opposite of Toolformer's *model-decides* policy and is currently unvalidated (invalidation register).
- `nally/tools/permissions.py` + `nally/config/permissions.json`: allow/ask/deny, last-pattern-wins, unknown→ask, skill overrides; audit notes headless auto-approve on `ask` when no UI emitter.
- `nally/agent/harness.py` + `task_router.py`: upstream intent/strategy routing that constrains which tools are even visible — Toolformer predicts this pre-constraint can hurt F1 if the model would have chosen better.
- `nally/tools/receipts.py` + `core/tracing.py`: existing execution evidence (JSONL + spans) that could support a Toolformer-style usefulness filter later, but no loss-based filtering exists today.

## Falsifiable hypothesis

- **H2 (tool selection, PRIORITY):** Removing `filter.py` deterministic preselection (LLM self-selects from full `registry.py` schemas) increases tool-use F1 and task success on stateful multi-dependency tasks vs current core-only/weak-cap policy, at the cost of larger per-call prompt + more candidate calls.
- **H2b (trigger):** A usefulness-gated trigger (call only when expected information gain high, Toolformer-style) beats both always-expose-core and top-k-forced triggers on precision without hurting recall.

## Measurable DV (where logged) + Phase 4 ablation

- DV: tool precision/recall/F1 per task (from `execute_result` success detector + `receipts.py`), task success + intermediate milestones (Phase 3 ToolSandbox-like suite), prompt tokens per call (`context.py` token counting), approval burden (`ask` rate).
- Ablation C (Phase 4): no-filter (full registry) vs current filter (core/weak-cap/strong-match) vs LLM-only with usefulness prompt; fixed tasks with tool dependencies (search→fetch→write→verify); report F1 × tokens × success.

## Expected counter-evidence (what refutes H2 here)

- If full-registry self-selection shows no F1 gain (or lower precision / more failed calls / higher latency) vs `filter.py` on the stateful suite, H2 refuted — deterministic pre-filter stays, and work shifts to tuning its matching instead.
- If no-filter blows context budget (`MAX_TOOL_OUTPUT`, pruning drops evidence) and degrades success, Toolformer's "generality preserved" claim does not transfer to this repo's context assembly — constraint is architectural, not model capability.
- If gains appear only on single-tool tasks but vanish on chained tasks (Toolformer allowed ≤1 call; authors' own QA-search limitation), H2b fails for NALLY's multi-step reality.

## Provider note (OpenCode/hy3-free vs Groq/Llama 3.3)

- Self-selection depends on function-call fidelity and schema adherence (native vs XML-like fallback in `graph.py`). Smaller/weaker caller → more malformed calls, arguing *for* a pre-filter on one provider but not the other. Phase 4 Ablation C must run on **both** providers; a filter that wins on Groq may lose on OpenCode and vice versa.

## Verdict

Not a design decision until ablation. Paper justifies A/B testing model-decided vs deterministic-preselected tool exposure — it does not justify current core set, weak-match cap, or any threshold.
