# Nally Engineering Subsystem

A closed-loop, autonomous software-engineering pipeline. It turns a high-level
task into a working, tested, production-quality project while keeping the rest
of Nally (chat, voice, web, Telegram) completely unchanged.

## What it does

The pipeline runs as a deterministic stage machine:

1. **Intake** — parse the raw task (goal, constraints, language hint).
2. **Clarify / Assumptions** — document sensible assumptions; ask at most one
   confirmation question only when the task is genuinely ambiguous.
3. **Brainstorm** — generate **at least 3** distinct approaches:
   - `simple`
   - `robust_scalable`
   - `creative_unconventional`
   using multi-path brainstorming, analogy-based thinking, constraint
   inversion, and alternative-architecture generation.
4. **Score** — each approach is scored 1–5 on feasibility, simplicity,
   maintainability, performance, and novelty, combined into a weighted total.
5. **Select / Merge** — pick the best (or merge the top two).
6. **Design + File Plan** — architecture summary, components, and a concrete
   file plan.
7. **Test Plan** — framework + concrete test cases.
8. **Implement** — generate complete files (no stubs/placeholders).
9. **Test / Lint / Build** — run the project's checks.
10. **Self-critique** — static review across edge cases, error handling,
    security, readability, performance, and maintainability.
11. **Refine** — feed failures + findings back and re-implement, up to a cap.
12. **Finalize** — emit code, tests, a `README.md`, `requirements.txt`,
    run commands, a `scorecard.json`, and known limitations.

## How to invoke it

### Option A — explicit CLI

```bash
python -m nally.engineering "Build a small CLI tool that organizes files by extension"
# or via the main entrypoint flag:
python main.py --engineer "Build a small CLI tool that organizes files by extension"
```

Requires a configured LLM key (`OPENCODE_API_KEY` or `GROQ_API_KEY` in `.env`).

### Option B — `build` skill (from chat)

When you explicitly ask Nally to *build / create / scaffold / generate* a full
project, the `build` skill activates and calls the `engineering_build` tool,
which runs the same loop deterministically. Ask a clarifying question first if
the intent is ambiguous.

## Architecture & testability

The loop depends only on two abstractions, both injectable:

- `LLMBackend` (`protocol.py`) — `NallyLLMBackend` (real) or `FakeLLMBackend` (tests).
- `Toolbox` (`toolbox.py`) — `RealToolbox` (reuses Nally's gated, sandboxed
  tools) or `FakeToolbox` (in-memory, for tests).

Because every LLM call and every filesystem/shell action goes through these
interfaces, the **entire loop is exercisable end-to-end with no API key and no
real side effects** via `FakeLLMBackend` + `FakeToolbox`. See
`tests/test_engineering_loop.py`.

## Safety

- All generated files are written under a controlled workspace
  (`data/builds/<slug>`) that the path-allowlist already permits.
- `RealToolbox` reuses Nally's existing permission gate: `deny` decisions are
  always blocked; `ask` decisions in this opt-in autonomous subsystem are
  auto-approved (logged) while destructive commands like `rm -rf` remain
  denied by policy.
- Command timeouts and secrets-scanning in the self-critique stage are enforced.

## Modules

| File | Responsibility |
|------|----------------|
| `models.py` | Data structures for the whole pipeline |
| `protocol.py` | `LLMBackend` + real/fake implementations |
| `toolbox.py` | `Toolbox` + real (gated) / fake implementations |
| `intake.py` | Task parsing + `is_full_build_request` classifier |
| `approaches.py` | Approach parsing + 3-category enforcement |
| `scoring.py` | Scoring, selection, merging |
| `plan.py` | Design / test-plan / implementation parsing |
| `review.py` | Static self-critique checks |
| `prompts.py` | Stage prompt templates (creativity techniques) |
| `workspace.py` | Sandboxed output dir + run manifest |
| `loop.py` | The deterministic orchestrator |
| `tool.py` | `engineering_build` tool registered with Nally |

## Tests

```bash
pytest tests/test_engineering_intake.py tests/test_engineering_scoring.py \
       tests/test_engineering_plan.py tests/test_engineering_review.py \
       tests/test_engineering_loop.py
```

The loop test proves: intake, ≥3 scored approaches, best-approach selection,
design/test-plan generation, implementation writes, test/lint execution,
critique-driven refinement, the refinement cap, and final README/manifest
output — all without a network or API key.
