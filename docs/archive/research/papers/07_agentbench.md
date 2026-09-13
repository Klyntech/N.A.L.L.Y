# 07 — AgentBench: Evaluating LLMs as Agents (Liu et al., 2023)

Source: https://arxiv.org/abs/2308.03688 (v1; HTML v1 inspected: abstract, §§1–4 structure, 8 envs, 25 LLMs)

## Finding (1–2 sentences)

LLMs must be judged as **interactive agents in multi-turn open-ended environments**, not as single-response text generators: across 8 diverse envs (OS, DB, KG, card game, lateral puzzles, ALFWorld, WebShop, WebBrowsing), top commercial models show agent ability while open-source models lag sharply — with long-term reasoning, decision-making, and instruction-following identified as the bottlenecks.

## Evidence strength

- 8 envs: 5 new (OS via Ubuntu Docker + bash + checking pipeline; DB via MySQL + select/insert/update + hash checks; KG on Freebase via query-tool APIs, ≥5 tool calls, F1/EM/executability; DCG Aquawar card battle vs baseline with win rate; LTP host-solver with Yes/No/Irrelevant + progress metrics) + 3 recompiled (ALFWorld 134 OOD, WebShop 500, Mind2Web).
- 25 LLMs (API + open 6B–30B); primitive CoT prompting (deliberately, to reflect practical use without multi-trial tricks); action-validity enforced (invalid bash/SQL/tool calls, format failures, repetition → fail).
- Reported pattern: GPT-4-class handles wide task range; open-source considerably behind despite competitive single-turn benchmark scores. Formalized as POMDP (S,A,T,R,U,O) interactive eval.
- Strength: breadth (code, query, game, puzzle, embodied, web) + real executors (Docker, MySQL, Virtuoso, game engine). Weakness: absolute numbers version-sensitive; CoT-only (no Reflexion/ToT comparison in main); simulator/host LLM (GPT-3.5) bias in LTP.

## Assumptions

- Text-only agents; open-ended generation mapped to env actions; 1-shot CoT formatting; round limits (e.g., OS 8); BLEU-fallback action matching in ALFWorld; budget-bounded sampling.

## NALLY mapping (Phase 0 audit facts)

- `nally/agent/harness.py` 6 classes + `task_router.py` 5 strategies: AgentBench predicts failure concentrates in COMPLEX/AMBIGUOUS/HIGH_STAKES long-horizon classes — exactly where NALLY routes to PLAN/DELEGATE/ENGINEERING without measured bottleneck data.
- `nally/tools/system.py` (RunCommand, SystemHealth) + `code.py` (RunCode, CodeAnalysis) + `gmail.py` + `websearch.py` + `fetch.py` + `mcp.py`: NALLY's env surface spans AgentBench's OS/DB/KG/Web axes — but current `tests/harness_eval` does not exercise them interactively.
- `nally/agent/scratchpad.py` + `sessions.py` (multi-session busy/queue) + `core.py` compaction: long-term reasoning substrate AgentBench says is the bottleneck; unmeasured here.
- `nally/engineering/` (autonomous build loop): closest to SWE/AgentBench-style sustained agency, but outside `harness_eval` coverage.

## Falsifiable hypothesis

- **H7 (overall agent eval):** On an AgentBench-like subset adapted to NALLY (OS command task in sandbox + DB-style memory query + KG-style multi-hop lookup + ALFWorld-like household file ops + WebShop-like search→choose→verify), NALLY's success ordered SIMPLE > KNOWLEDGE > CREATIVE > COMPLEX > AMBIGUOUS, with the COMPLEX→AMBIGUOUS gap largest — and instruction-following (valid action rate) explains more variance than plan quality.
- **H7b (routing):** `harness.py` LLM classifier + `task_router.py` promotion improves aggregate AgentBench-like score vs regex-fallback alone, specifically by keeping SIMPLE/KNOWLEDGE on DIRECT/REACT and reserving PLAN for COMPLEX/HIGH_STAKES.

## Measurable DV (where logged) + Phase 4 ablation

- DV: per-env success rate, valid-action rate (parseable + executable), avg turns-to-success, repetition-fail rate (3× identical output rule), per-class breakdown; all from `tracing.py` + `receipts.py` + executor logs.
- Phase 3 build: AgentBench-like suite (5–6 envs, sandboxed commands, deterministic checkers like OS checking pipeline / DB hash compare); Phase 4 runs routing Ablation (LLM-classifier vs regex-fallback vs no-routing) on it.

## Expected counter-evidence (what refutes H7 here)

- If open-vs-commercial gap does not replicate within NALLY's providers (Llama 3.3 ≈ hy3-free on agent tasks) or SIMPLE≈COMPLEX success, H7's bottleneck ordering fails for this repo — likely because NALLY tasks are narrower than AgentBench's 8-env spread.
- If invalid-action rate is low (<5%) yet success still low, the bottleneck is planning/grounding, not instruction-following — redirect work from formatting to retrieval/context (H3) and planning gates (H4).
- If regex-fallback matches LLM classifier on aggregate agent score, H7b fails — keep the cheap path and spend budget elsewhere.

## Provider note (OpenCode/hy3-free vs Groq/Llama 3.3)

- Paper's central result *is* a provider/capability gap. Expect the same ordering question inside NALLY: run the AgentBench-like suite on **both** providers and report per-env profiles; a routing policy tuned on the stronger provider may collapse on the weaker (especially on OS/DB exact-syntax tasks).

## Verdict

Not a design decision until built and run. Paper justifies **multi-env interactive eval with validity enforcement** as the overall agent yardstick — it does not justify any NALLY routing threshold or strategy default.
