# 03 — Lost in the Middle: How Language Models Use Long Contexts (Liu et al., 2023) — PRIORITY 1

Source: https://arxiv.org/abs/2307.03172 (v3; HTML v3 inspected, §§1–5)

## Finding (1–2 sentences)

More context ≠ better use: performance follows a U-shape (best at very beginning/primacy and end/recency, worst in the middle), longer inputs can score *below closed-book*, and extended-window variants perform nearly identically to base models when the input fits both.

## Evidence strength

- Multi-document QA (NaturalQuestions-Open, 2655 paragraph-answer queries; Contriever distractors; k=10/20/30 docs; accuracy = answer appears): GPT-3.5-Turbo drops >20% middle vs edges; 20/30-doc middle can underperform closed-book 56.1% vs oracle 88.3%. Identical curves for GPT-3.5 vs 16K and Claude-1.3 vs 100K when input fits both.
- Synthetic key-value (UUID JSON, k=75/140/300): Claude-1.3 perfect, others U-shaped; query-before-*and*-after fixes key-value to near-perfect but barely moves multi-doc QA.
- Architecture: encoder-decoder (Flan-UL2/T5-XXL) robust only *within* training-time length (1.9% best-worst gap); longer → U-shape returns. Base (non-instruct) MPT-30B already U-shaped; instruct tuning slightly narrows gap (10%→4%) but preserves shape. Llama-2 7B recency-only; 13B/70B U-shaped.
- Open-domain QA case study: reader saturates far before retriever recall; 20→50 docs only +1.5% (GPT-3.5) / +1% (Claude-1.3) despite longer context + latency/cost.
- Strength: controlled position × length grid across open/closed models + ablations (distractor order, ambiguity, GPT-4 subset). Weakness: QA/retrieval only, greedy decoding, no tool-use/agent-loop setting; absolute numbers model- and prompt-sensitive.

## Assumptions

- Prompt = task spec + documents + query-at-end (unless query-aware variant); decoder-only attends only to prior tokens during document encoding.
- Relevance is single-position (exactly one gold doc / one key); distractors ranked by relevance.
- Claim is about *use*, not *capacity*: window fits input in all comparisons.

## NALLY mapping (Phase 0 audit facts) — highest leverage

- `nally/agent/core.py` 8-stage assembly is precisely the risk surface: user msg → guardrails → harness/task_router → scratchpad → skills (+design-skill) → pruning → compaction → **memory injection after first system msg / before first user msg** → **summary injection at index 1** → **auto websearch injection (time-sensitive)** → **scratchpad insertion** → re-prune → tool-surface selection → `graph.py` **receipt injection as system msg immediately before `llm_call`**.
- `nally/agent/context.py`: tiktoken-or-char counting; truncates large tool msgs on a *copy*; drops old assistant/tool when over budget (preserves user/system); compaction keeps system + recent, summarizes older (LLM fallback); category-based project/auto-fact recall.
- `nally/agent/platform.py`: OS/arch/shell/Python/cwd/commands formatted into system prompt (more middle mass).
- Implication: NALLY's "middle" (memory@idx1, summary@idx1, websearch, older conversation, tool schemas) is where gold context can be buried; receipts at the end benefit from recency but may crowd out the question. Current ordering is documented, **not validated**.

## Falsifiable hypothesis

- **H3 (context architecture, PRIORITY 1):** Permuting the assembly order changes task success and recall on this branch: placing task-critical evidence (retrieved docs, memory hits, receipts relevant to the current question) at the **beginning (after system) or end (just before the query/tool call)** beats burying it in the middle; adding more retrieved docs beyond ~20 shows saturating gains while increasing tokens/latency.
- **H3b (query-aware):** Repeating the user query (or a compressed intent from `harness.py`) *before* the document/memory block *and* at the end improves multi-doc/stateful performance vs query-at-end-only, mirroring the paper's key-value fix — but may not rescue badly-ranked content.

## Measurable DV (where logged) + Phase 4 ablation

- DV: task success + best-vs-worst position gap (U-depth), recall of gold doc/memory (did the model cite/use it?), tokens + latency per call (`context.py` usage tracking, `tracing.py` spans), pruning drop rate.
- Ablation A (Phase 4): ≥4 permutations of `system + memory + tools + conversation + retrieved` (e.g., A: current; B: retrieved+memory-first; C: retrieved-last before query; D: query-repeated both ends + reranked retrieved first) × doc budgets (10/20/30 or token equivalents); fixed tasks requiring mid-context facts; report success × U-gap × cost. Include rerank/truncate variant (paper §5 prescription).

## Expected counter-evidence (what refutes H3 here)

- If all permutations score within ±2% success and similar U-gap on the stateful suite, H3 refuted for this repo — ordering is not the lever; focus shifts to retrieval quality / pruning budgets instead.
- If more context monotonically helps (no saturation to 30+ docs) on NALLY tasks, the paper's saturation claim does not transfer — likely because NALLY tasks are tool-chained rather than single-doc QA.
- If query-repetition shows zero gain on both QA and stateful tasks, H3b fails here (paper itself found minimal QA gain; key-value ≠ agent reasoning).

## Provider note (OpenCode/hy3-free vs Groq/Llama 3.3)

- U-shape depth is model- and length-sensitive (paper: 7B recency-only vs 70B U-shape; extended ≠ better). Llama 3.3 vs hy3-free may differ in effective use of the same assembly. Phase 4 Ablation A must run on **both**; a "best order" found on one provider is not portable until replicated.

## Verdict

Not a design decision until ablation. Paper justifies testing placement + budget + rerank/truncate as a **context architecture matrix** — it does not justify any specific NALLY ordering, `MAX_MEMORIES_INJECTED`, or compression threshold.
