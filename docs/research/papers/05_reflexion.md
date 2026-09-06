# 05 — Reflexion: Language Agents with Verbal Reinforcement Learning (Shinn et al., 2023)

Source: https://arxiv.org/abs/2303.11366 (v1; HTML v1 inspected, §§1–4)

## Finding (1–2 sentences)

Verbal self-reflection on failed trials, stored as episodic memory and re-injected on retry — without weight updates — converts one-shot ReAct into a trial-and-error learner: reflection corrects hallucinated loops and inefficient plans by naming the mistake and prescribing a concrete next-trial plan.

## Evidence strength

- ALFWorld (134 envs, ReAct base): 63% trial-1 → **97% within 12 trials** (4 unsolved); baseline retry without reflection shows no such learning curve (retry ≠ learning). Heuristic triggers reflection on repeat-cycles > Ω or steps > ε.
- HotPotQA (100 Qs, EM reward): Reflexion 32% trial-1 → **54% by trial 6–7** (+22pp), beating base ReAct retry (+0pp, stuck at 34%); each consecutive trial improves, showing accumulating memory value. Reflection examples show query reformulation (Grown-Ups → Sam Kelly) after diagnosing wrong search.
- Failure split: hallucination (≥2 identical action+obs cycles) dominates; with reflection, inefficient-planning errors corrected except 4 residual hallucinations (~3:1 ratio preserved in baseline, broken with reflection).
- Negative result: WebShop (100 tasks) 33%→35% with Reflexion vs 33%→34% retry — no intuitive reflections generated; authors attribute to search-engine quality bottleneck, not reasoning.
- Strength: binary reward only (success/fail), ≤3 reflections in memory, no domain solutions in reflection prompts. Weakness: GPT-3/3.5-era, small HotPotQA slice, heuristic hand-tuned, extra trials = extra cost; WebShop failure bounds generality.

## Assumptions

- ReAct base policy; resettable environment for retries; binary success signal (engine query / EM); reflection LLM prompted with 2 domain-specific failed-trajectory→reflection exemplars.
- Memory = short list (≤3) of natural-language reflections prepended on next trial; termination on success, no-improvement, or max trials.

## NALLY mapping (Phase 0 audit facts)

- `nally/memory/reflector.py`: hourly background reflection (daily reflections, conversation summaries, episodes, semantic patterns, user facts; prompts forbid credentials) — batch/offline, not trial-gated like Reflexion.
- `nally/memory/store.py` + `models.py`: memories/episodes/conversations/patterns with SQLite FTS5 (SQLite) vs non-FTS Postgres; retrieval-time injection path exists.
- `nally/memory/confidence.py`: pure decay (1.0/0.9/0.7/0.5/0.3 buckets) + fixed boost capped — unvalidated schedule (invalidation register).
- `nally/agent/graph.py`: consecutive-error + total-tool-call breakers, completion gate (TASK NOT COMPLETE), claim-verification correction — natural triggers for a Reflexion-style retry, but no verbal-reflection-on-failure loop exists today.
- `nally/agent/scratchpad.py` + `core/tracing.py`: per-request working memory + nested spans — could carry trial-1 failure → reflection → trial-2 plan, currently unused that way.

## Falsifiable hypothesis

- **H5 (reflection + memory):** Adding a failure-triggered verbal reflection (heuristic: repeat-cycle or consecutive-error breaker fires, or `verifier.py` flags contradicted/fabricated claims) that writes a concise lesson to episodic memory and retries once improves success on recoverable-failure tasks (ALFWorld-like navigation, multi-hop QA with reformulable queries) vs blind retry, without weight updates.
- **H5b (schedule):** Hourly batch reflection + time-bucket decay is *not* the active ingredient; trial-gated reflection with retrieval at next-attempt time drives the gain. Disabling `reflector.py` hourly while keeping trial-gated reflection should preserve most of the lift.

## Measurable DV (where logged) + Phase 4 ablation

- DV: trial-1 → trial-2 success delta (learning curve, not just accuracy), hallucination-loop rate (repeat action+obs cycles from `tracing.py`/`receipts.py`), inefficient-planning rate (steps-to-success), reflection helpfulness (did trial-2 avoid the named mistake?), added tokens/trials cost.
- Ablation E (Phase 4): blind-retry vs heuristic-triggered-reflection vs reflection-on-every-failure; with/without hourly `reflector.py`; with/without decay (`confidence.py` flat vs bucketed); report delta-success × loop-rate × cost. Include a WebShop-like tool-quality-bottleneck task to test the paper's negative result.

## Expected counter-evidence (what refutes H5 here)

- If reflection-retry matches blind-retry deltas (±2pp) while costing extra LLM calls, H5 refuted — NALLY failures are tool-quality or context-placement bound (cf. ToolSandbox/WebShop notes), not memory bound.
- If hourly reflection alone matches trial-gated reflection, H5b fails — keep current `reflector.py` schedule and skip per-failure machinery.
- If reflections are generic ("try harder") and trial-2 repeats the same loop (repeat-cycle rate unchanged), the emergent self-reflection property does not transfer to Llama 3.3 / hy3-free at current prompting — needs different reflection prompts or a stronger reflector model.

## Provider note (OpenCode/hy3-free vs Groq/Llama 3.3)

- Reflection quality is generator-sensitive (paper used GPT-3/3.5). Llama 3.3 vs hy3-free may differ sharply at diagnosing their own loops. Phase 4 should test reflector = same vs stronger model; do not assume self-reflection transfers equally.

## Verdict

Not a design decision until ablation. Paper justifies testing a **failure-gated verbal reflection + episodic retry** loop — it does not justify the hourly schedule, decay buckets, or any memory-injection budget.
