# 08 — SWE-bench: Can Language Models Resolve Real-World GitHub Issues? (Jimenez et al., 2023)

Source: https://arxiv.org/abs/2310.06770 (v1; HTML v1 inspected, §§1–5)

## Finding (1–2 sentences)

Real repo work — navigate thousands of files, localize the fault, coordinate edits across functions/files, and pass fail-to-pass + regression tests — defeats SOTA LMs: even with oracle file retrieval, Claude 2 resolves 4.8% and GPT-4 1.7%; with BM25 retrieval, 1.96% and 0.0% — proving retrieval/localization and cross-context editing, not prose fluency, are the gates.

## Evidence strength

- 2294 tasks across 12 popular Python repos (avg issue 195 words; codebase ~3010 files / 438K lines; gold patch ~1.7 files, 3.0 funcs, 32.8 lines; ~9.1 fail-to-pass + ~120 total tests). 3-stage pipeline (repo select → attribute filter → execution filter); patch-applied + test-run verdict; continually updatable.
- Baselines: BM25 vs oracle retrieval; patch-vs-whole-file (patches win: Claude 2 oracle 4.8% vs whole-file 2.2%); collapsed-oracle (only ±15 lines around gold edits) lifts GPT-4 1.3%→3.4%, Claude 2 4.8%→5.9% — localization dominates.
- Difficulty correlates with total context length (performance drops as input grows even as BM25 recall rises); models emit shorter/simpler edits than gold (applied patches ~half gold length, rarely multi-file); finetuned SWE-Llama-7B/13B (LoRA on 10k oracle-context instances) competitive with Claude 2 in oracle setting but collapses under BM25 distribution shift.
- Strength: execution-grounded, multi-file, regression-checked. Weakness: Python-only, test-passing ≠ maintainable/readable, image-bearing issues penalize text-only models, absolute numbers stale (frontier moved since 2023).

## Assumptions

- Issue text + full codebase in, patch out; unix-patch applies cleanly; repo tests as oracle; retrieval (BM25/oracle) selects files into a fixed token budget; single-shot patch (no agent loop in main baselines).

## NALLY mapping (Phase 0 audit facts)

- `nally/engineering/` (autonomous loop via `python -m nally.engineering` / `--engineer`): the repo's sustained code-editing agent — unmeasured against anything SWE-bench-like.
- `nally/tools/code.py` + `files.py` (ReadFile, FileOps) + `system.py` (RunCommand) + `graph.py` file-state checkpoints + project snapshots/diffs: the localization → edit → test machinery SWE-bench says is the bottleneck; `MAX_TOOL_OUTPUT` truncation + pruning directly threaten localization (cf. collapsed-oracle gain).
- `nally/agent/context.py` + `core.py` assembly: full-file stuffing into context predicts the paper's length-degrades-performance curve; retrieval precision (which files, how many lines) matters more than window size.
- `nally/tools/receipts.py` + `verifier.py` + `tracing.py`: patch-vs-test evidence trail exists, but no fail-to-pass/pass-to-pass harness exists in `tests/` today.

## Falsifiable hypothesis

- **H8 (coding-agent eval):** On a NALLY-scoped SWE-bench-like suite (real issues in this repo + fail-to-pass/regression tests, multi-file edits required), an agent loop (localize → edit → run tests → repair) with **tight retrieved context** (oracle-collapsed style: relevant hunks ± lines, not whole files) beats single-shot whole-file regeneration and beats BM25-full-file stuffing — and model success drops as stuffed context grows despite higher recall.
- **H8b (retrieval):** BM25 file retrieval underperforms a localization agent (search tools + execution feedback) on resolve rate; finetuning-free retrieval tuning does not close the gap.

## Measurable DV (where logged) + Phase 4 ablation

- DV: resolve rate (fail-to-pass + no regression), apply rate (patch parses/applies), localization accuracy (edited files/funcs overlap gold), patch size vs gold, context tokens per task; from test-runner logs + `tracing.py` + `receipts.py`.
- Phase 3 build: `tests/eval/coding/` with containerized test runs (mirroring SWE-bench execution validation; reuse `graph.py` snapshots/diffs for safety); Phase 4 ablations: tight-hunk vs full-file vs BM25-stuffed contexts × single-shot vs loop-with-test-feedback.

## Expected counter-evidence (what refutes H8 here)

- If whole-file regeneration matches tight-hunk patches on resolve rate for NALLY-sized tasks, H8 fails here — this repo's edits are smaller/more localized than SWE-bench's 438K-line codebases, so stuffing cost is affordable.
- If BM25-stuffed context monotonically helps (no length-degradation), the localization crisis does not transfer — likely because NALLY file counts are small vs SWE-bench scale.
- If test-feedback loops show zero lift over single-shot (models ignore execution output), the agent-loop investment is unjustified for coding tasks here; redirect to retrieval precision instead.

## Provider note (OpenCode/hy3-free vs Groq/Llama 3.3)

- Absolute resolve rates are frontier-sensitive (2023 numbers obsolete as ceilings, valid as *pattern*: oracle≫BM25, tight≫stuffed, loop>single-shot). Re-run the pattern on **both** current providers; expect patch-format fidelity (native vs XML-like fallback in `graph.py`) to differ by provider and confound resolve-vs-apply rates — report both separately.

## Verdict

Not a design decision until built and run. Paper justifies a **scoped execution-grounded coding suite with retrieval ablations** — it does not justify any NALLY retrieval limit, hunk size, or engineering-loop default.
