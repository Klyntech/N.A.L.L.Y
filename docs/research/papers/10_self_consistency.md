# 10 — Self-Consistency Improves Chain of Thought (Wang et al., ICLR 2023) + Supporting: CoT, Least-to-Most, Uncertainty of Thoughts

Sources:
- Self-Consistency: https://arxiv.org/abs/2203.11171 (v2; HTML v2 inspected, §§1–3)
- CoT: https://arxiv.org/abs/2201.11903 (Wei et al., NeurIPS 2022; abstract + cited method)
- Least-to-Most: https://arxiv.org/abs/2205.10625 (Zhou et al., ICLR 2023; abstract)
- Uncertainty of Thoughts: https://arxiv.org/abs/2402.03271 (NeurIPS 2024; abstract + search-extracted method/results)

## Finding (1–2 sentences)

Don't trust one reasoning path: **CoT** elicits intermediate steps that unlock reasoning; **Self-Consistency** samples diverse paths and takes the plurality answer, lifting accuracy massively (e.g., GSM8K 56.5%→74.4% PaLM-540B); **Least-to-Most** chains easy→hard subproblems for compositional generalization (SCAN length-split 16%→99%); **Uncertainty of Thoughts (UoT)** closes the loop for information-seeking by simulating futures, scoring candidates with information-gain rewards, and asking the question with max expected reward (+38.1% success avg, beating CoT-SC +33.8pp, Reflexion +29.9pp, ToT variants).

## Evidence strength

- Self-Consistency: LaMDA-137B / PaLM-540B / GPT-3-code-davinci across arithmetic (AddSub, MultiArith, ASDiv, AQuA, SVAMP, GSM8K) + commonsense (CommonsenseQA, StrategyQA, ARC). PaLM deltas: GSM8K +17.9, AQuA +12.5, SVAMP +7.6, StrategyQA +6.3, ARC-C +3.5 — SOTA without training/verifier. Sampling T=0.5–0.7, top-k=40, m=40 paths (10 runs, σ<0.5). More paths monotonic with diminishing returns; robust to T/k; beats prompt-permutation ensembles (1–2pp vs 4–7pp) and sample-and-rank; plurality > likelihood-weighting (poor calibration); consistency% correlates with accuracy ("knows when it doesn't know"); robust to imperfect prompts (GSM8K 14.9→23.4 with 40 paths).
- CoT: 8 exemplars → SOTA GSM8K on 540B; emergent with scale; foundation for all above.
- Least-to-Most: 14 exemplars → ≥99% SCAN any split (vs 16% CoT); symbolic/compositional/math gains via sequential subproblem solving grounded in prior answers.
- UoT (medical/troubleshooting/20-Questions, 5 datasets × 5 LLMs incl. Llama3-70B +46.6%): candidate questions → multi-step possibility-tree simulation → Ru (information gain) → Ra/Re propagation → ask max-Re; beats DP/CoT/CoT-SC/Reflexion/ToT; one-step planning already effective; depth capped at 3 for budget; pruned variant still beats adapted ToT +7.36%.
- Strengths: unsupervised, off-the-shelf, no verifier training. Weaknesses: N× cost (40 paths in paper!); fixed-answer assumption (plurality needs parseable answers); UoT simulation depth/budget capped; absolute numbers model-era-bound.

## Assumptions

- SC: fixed answer set, parseable "The answer is X", diverse decodes available (T>0), plurality ≈ correctness (diverse-correct converge, incorrect scatter).
- L2M: decomposable tasks with verifiable subanswers.
- UoT: possibility set Ω modelable (closed) or constructible (open); simulator LM faithful; information-gain reward computable from simulated futures.

## NALLY mapping (Phase 0 audit facts)

- `nally/agent/verifier.py` + `nally/tools/receipts.py` + `graph.py` final-response path: deterministic receipt-grounded check (supported/contradicted/fabricated) + LLM correction + completion gate — the **cheap alternative** to N-sampling. SC predicts sampling helps where verifier is blind (no receipts: pure reasoning answers).
- `nally/agent/harness.py` classifier (class/confidence/reasoning JSON): the natural **uncertainty signal** for a UoT-style gate (ask vs commit vs plan) — currently a routing input, not an information-gain optimizer.
- `nally/agent/human_checkpoint.py` (COMPLEX/HIGH_STAKES/CREATIVE review, fail-closed): SC/UoT predict many "uncertain" cases could be resolved by sampling or a clarifying question *before* expensive human review.
- `nally/thinking/tool.py` + `engine.py`: strategy fan-out exists but no plurality vote or consistency-scored confidence; `NALLY_THINKING_MAX_STRATEGIES=3` is a cap, not a validated sample count.
- Gap: no consistency metric ("knows when it doesn't know"), no L2M chaining in `planner.py` flat steps, no UoT simulation of candidate questions for AMBIGUOUS tasks.

## Falsifiable hypothesis

- **H10 (verification/judging):** On reasoning-heavy tasks with fixed answers, Self-Consistency (m=3–5 sampled paths + plurality) beats single-path + `verifier.py` receipt check on accuracy, but at 3–5× cost; on tool-grounded tasks with receipts, single-path + `verifier.py` matches SC at far lower cost — so sampling should be **gated to low-consistency / no-receipt cases**, not always-on.
- **H10b (uncertainty gate):** For AMBIGUOUS tasks, a UoT-lite policy (generate candidate clarifications/next-actions, score by expected information gain using `harness` confidence + simulated answers, ask/act on max-Re) beats direct-answer and beats always-plan on success per cost.

## Measurable DV (where logged) + Phase 4 ablation

- DV: accuracy/success, consistency% (agreement rate → calibration curve), verifier catch rate (supported/contradicted/fabricated), questions-to-success (efficiency, UoT metric), tokens/calls/wall time (`tracing.py`), human-review rate (`human_checkpoint.py` events).
- Ablation D (Phase 4): single-path vs single+verifier vs SC-3 vs SC-5 on reasoning vs tool-grounded splits; UoT-lite (candidate-score-ask) vs direct vs full-PLAN on AMBIGUOUS tasks; report accuracy × cost + calibration (does low consistency predict failure?).

## Expected counter-evidence (what refutes H10 here)

- If SC-3/5 shows <2pp gain over single+verifier on *both* splits, H10 refuted — sampling cost unjustified here (likely: Llama 3.3 / hy3-free diversity too low at affordable T, or verifier already covers the failure modes).
- If consistency% does not correlate with accuracy (flat calibration), the "know when it doesn't know" signal fails — cannot gate sampling/human-review on agreement.
- If UoT-lite's clarifying questions show no efficiency gain (same questions-to-success as direct), AMBIGUOUS tasks here are not information-seeking bound (cf. Reflexion/WebShop tool-quality bound) — keep direct/plan routing instead.

## Provider note (OpenCode/hy3-free vs Groq/Llama 3.3)

- SC gains scale with base-model diversity and instruction-following (paper: consistent across LaMDA/PaLM/GPT-3 but magnitudes differ; UoT: Llama3-70B +46.6% largest). Expect provider divergence in optimal T, m, and plurality reliability. Run Ablation D on **both**; calibrate consistency thresholds per provider — do not share one threshold.

## Verdict

Not a design decision until ablation. Papers justify testing **gated sampling (SC-3/5) + consistency calibration + UoT-lite ask-gate** against the cheap receipt-verifier baseline — they do not justify any sample count, temperature, consistency threshold, or always-on judging.
