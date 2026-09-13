# 09 — Tree of Thoughts: Deliberate Problem Solving with LLMs (Yao et al., NeurIPS 2023)

Source: https://arxiv.org/abs/2305.10601 (v2; HTML v2 inspected, §§1–4)

## Finding (1–2 sentences)

Generalizing CoT from a single left-to-right chain to a **tree of coherent thoughts** with LM-generated candidates, LM self-evaluation (value/vote), and classical search (BFS/DFS with lookahead/backtracking/pruning) unlocks tasks where CoT collapses: Game-of-24 4%→74% (b=5), crosswords word-success <16%→60%, creative-writing coherence preferred 41 vs 21 pairs.

## Evidence strength

- Game-of-24 (100 hard games): IO 7.3%, CoT 4.0%, CoT-SC-100 9.0%, IO-best-of-100 33%, CoT-best-of-100 49% vs ToT-b1 45%, ToT-b5 74%. Error analysis: ~60% of CoT fails at step 1 (first 3 words) — left-to-right decoding commits too early.
- Crosswords (20 5×5 games): letter/word/game IO 38.7/14/0, CoT 40.6/15.6/1 vs ToT 78/60/20 (oracle-best-state 82.4/67.5/35); ablations: no-prune 65.4/41.5/5, no-backtrack(greedy) 54.6/20/5 — backtracking + pruning both matter; evaluator imperfection noted (rare words pruned wrongly).
- Creative writing (100 4-sentence inputs): GPT-4 coherence ToT 7.56 vs CoT 6.93 vs IO 6.19; human blind preference ToT>CoT 41, CoT>ToT 21; iterative-refine lifts both (IO 6.19→7.67, ToT→7.91) — refinement as third generator type.
- Framework: thought size tuned per task (equation / word / paragraph plan); generators (i.i.d. sample vs propose-sequentially); evaluators (independent value sure/maybe/impossible ×3 samples vs cross-state vote ×5); BFS (b≤5, T≤3) vs DFS (≤100 steps, value-threshold prune + backtrack).
- Strength: IO/CoT/CoT-SC/self-refine as special cases (limited depth/breadth); modularity (LM, decomposition, G, V, search independently variable). Weakness: GPT-4-only main results (GPT-3.5 appendix weaker), high API cost, prompt-sensitive valuation, toy puzzles vs stateful tool tasks.

## Assumptions

- Off-the-shelf LM (no training); coherent-thought granularity chosen by human per task; evaluator LM ≈ capable reasoner (self-evaluation trusted); search budget fixed (breadth/depth caps); ground-truth feedback only in refine baseline, not in ToT core.

## NALLY mapping (Phase 0 audit facts)

- `nally/thinking/engine.py`: heuristic keyword strategy selection + parallel strategies + synthesis LLM call — a **single-shot fan-out**, not a searched tree with value/backtrack. ToT predicts this underperforms deliberate search on pivotal-early-decision tasks.
- `nally/agent/planner.py`: flat ordered steps + critique + replan loop — closest to ToT's DFS/backtrack, but steps are linear, branching factor = 1, no candidate-value selection.
- `nally/agent/harness.py` + `task_router.py`: route to PLAN vs REACT is the "when is search worth it" gate ToT §6 says to tune (ToT unnecessary where GPT-4 already excels — GSM8K/StrategyQA appendix).
- `nally/thinking/strategies.py` + `prompts.py` + `NALLY_THINKING_MAX_STRATEGIES`/`TIMEOUT`: natural knobs for G (k candidates) and V (votes) if a ToT path is tested.
- Supporting **Least-to-Most** (Zhou et al., ICLR 2023; SCAN length-split 16%→99% via solve-easy-first chaining): maps to `planner.py` step ordering — subproblem answers feed harder steps; untested whether NALLY decomposition actually chains or merely lists.

## Falsifiable hypothesis

- **H9 (deliberate search):** For tasks with pivotal early decisions (multi-step tool chains where step-1 choice conditions all later calls), a ToT-style path — generate k≥3 candidate next-steps, LM-value/vote, keep top-b, backtrack on `verifier.py`/execution failure — beats linear CoT/ReAct and single-shot ThinkTool fan-out on success, at 3–10× token cost. On routine SIMPLE/KNOWLEDGE tasks it ties or loses on cost-adjusted success and should be gated off.
- **H9b (decomposition):** Least-to-most ordering (easy verifiable subproblems first, answers injected) beats flat plan order on compositional tasks.

## Measurable DV (where logged) + Phase 4 ablation

- DV: success rate, cost (tokens, LLM calls, wall time via `tracing.py`), backtrack rate, prune precision (pruned branches that were truly dead), best-state-vs-output gap (oracle check like paper's +best-state).
- Ablation D2 (Phase 4): linear (CoT/ReAct) vs fan-out (current ThinkTool) vs ToT-BFS(b=3) vs ToT-DFS(prune+backtrack) on pivotal-decision tasks + routine controls; report success × cost Pareto + gate accuracy (did router correctly skip ToT on easy tasks?).

## Expected counter-evidence (what refutes H9 here)

- If ToT variants match linear success within ±2pp while costing ≥3× tokens, H9 refuted for this repo — early decisions are not pivotal in NALLY's tool domains (or the evaluator LM cannot value branches reliably).
- If value/vote accuracy ≈ chance (best-state ≫ output, or prune kills good branches at high rates like the paper's rare-word case), self-evaluation does not transfer to Llama 3.3 / hy3-free — ToT's heuristic core fails here regardless of budget.
- If Least-to-Most ordering shows no gain over flat plans, decomposition benefit is task-specific (SCAN-like compositionality absent in NALLY tasks).

## Provider note (OpenCode/hy3-free vs Groq/Llama 3.3)

- ToT depends twice on LM quality (generator diversity + evaluator judgment). Paper's GPT-4→GPT-3.5 drop warns the effect may vanish on weaker providers. Run Ablation D2 on **both**; consider heterogeneous mapping (strong model as evaluator, cheap model as generator) if same-model ToT fails on one provider.

## Verdict

Not a design decision until ablation. Paper justifies testing **gated deliberate search with value + backtrack** on hard subsets — it does not justify always-on ToT, any breadth/depth/vote count, or replacing the current ThinkTool.
