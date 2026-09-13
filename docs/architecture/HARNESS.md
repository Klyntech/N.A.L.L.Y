# Nally Harness v2

The **Harness** is Nally's intent-classification + task-routing layer. It decides
*what kind* of task a request is, then routes it through the right pipeline
stages — direct answer, generate→critique→revise, scratchpad working memory,
or tool-result verification.

It is the middleware between the user's raw message and the ReAct agent loop:
every request is classified into one of six **task classes**, and each class has
its own pipeline of **stages** that are independently toggleable.

> Status: **main** feature. Gate disabled by default via `NALLY_HARNESS_ENABLED=false`.
> Turn it on to route request through classification + staged pipelines.

- **Module**: `nally/agent/harness.py` (classification, critique, tool verification)
- **Module**: `nally/agent/scratchpad.py` (per-request working memory)
- **Integration**: `nally/agent/core.py`, `nally/agent/graph.py`
- **Tests**: `tests/test_harness.py`, `tests/harness_eval/`
- **Config source of truth**: `nally/config.py` (`HARNESS_*` block)

---

## 1. Overview

```
User message
     │
     ▼
┌──────────────────────────┐   NALLY_HARNESS_ENABLED  (off by default)
│ Intent Classifier        │   classify_intent()
│ (LLM, regex fallback)    │   → TaskClass + confidence + method
└───────────┬──────────────┘
            ▼
   Classification (task_class)
            │
            ▼
┌──────────────────────────┐   get_pipeline_config(task_class)
│ Pipeline Config          │   direct_answer / critique / scratchpad / tool_verify
│ (per task class)         │   (NALLY_HARNESS_PIPELINES override)
└───────────┬──────────────┘
            ▼
  Stages fire per config:
   • SIMPLE/KNOWLEDGE/AMBIGUOUS ─ direct ReAct answer
   • CREATIVE/COMPLEX/HIGH_STAKES ─ generate→critique→revise (+ scratchpad on complex/high-stakes)
   • every tool call ─ tool-result verification  (complex/creative/high-stakes)
```

The classifier itself is a **cheap** LLM call (or a pure regex pass when no LLM
is provided). It deliberately does **not** use the same expensive model reserved
for the actual task. Every stage is independently disable-able.

---

## 2. Task Classes

Six mutually-exclusive classes (`nally/agent/harness.py::TaskClass`):

| Class | Value | Meaning |
|-------|-------|---------|
| `SIMPLE` | `SIMPLE` | Greetings, quick factual answers, short commands. |
| `KNOWLEDGE` | `KNOWLEDGE` | Explanations, comparisons, research ("how does X work"). Correct info, no creation. |
| `CREATIVE` | `CREATIVE` | Writing, drafting, storytelling, code authoring, ideation. Needs original output. |
| `COMPLEX` | `COMPLEX` | Multi-step tasks, builds, deployments, integrations, migrations. Needs planning + tools. |
| `AMBIGUOUS` | `AMBIGUOUS` | Unclear intent; could map to multiple classes. Ask or best-guess. |
| `HIGH_STAKES` | `HIGH_STAKES` | Production changes, deletions, security, billing, financial. Extra caution. |

---

## 3. Intent Classification

`nally/agent/harness.py::classify_intent(text, llm_call_fn=None, override=None)`

Priority order:

1. **Manual `override`** — hard-codes a class (`method="override"`, confidence `1.0`). Bypasses everything.
2. **LLM** (`classify_by_llm`) — one cheap call, `temperature=0`. Parses strict JSON:
   `{"class":"CLASS_NAME","confidence":0.0-1.0,"reasoning":"..."}`. Wire `llm_call_fn`
   with `(messages, temperature) -> str`.
3. **Regex fallback** (`_classify_regex`) — zero model cost, deterministic.

The LLM path **always** degrades to regex on: non-JSON output, an unknown class
value, or any exception. So the harness never hard-fails on a flaky model.

### Regex heuristics

Order matters — first match wins (most specific/dangerous first):

| Priority | Signals |
|----------|---------|
| 1. HIGH_STAKES | deploy/production/ship/release/push-to; delete/remove/drop/destroy/wipe + db/table/production/server; migration/rollback/revert; security/vulnerability/breach/auth; billing/payment/financial/invoice. |
| 2. CREATIVE | write/draft/compose/story/poem/essay/blog-post; design/imagine/brainstorm/ideate; refactor/rewrite/reimagine + code/prose/text. |
| 3. KNOWLEDGE | what/how/why/when/where/who...; explain/tell-me-about/define/describe; difference-between/compare/vs; why-does/how-does (only when **no** action keyword present). |
| 4. COMPLEX | implement/build/create/set-up/configure/install; multiple/several/many/all-of; step-by-step/plan/organize/orchestrat; integrate/connect/wire/link + with/to/and; migrate/upgrade/refactor. Heuristic bonus: ≥3 sentences, or an action keyword. Needs ≥2 to trigger. |
| 5. SIMPLE | hey/hi/hello/thanks/ok/yes/no/lol/haha; who-am-i/what's-your; remember/recall/forget; short (≤20 token) question; <30 words with no action keyword and <2 sentences. |
| 6. default | AMBIGUOUS. |

```python
from nally.agent.harness import classify_intent

c = classify_intent("deploy the app to production")
print(c.task_class)   # TaskClass.HIGH_STAKES
print(c.confidence)   # 0.75
print(c.method)       # "regex"  (or "llm" if an LLM was used)
```

---

## 4. Pipeline Config (per task class)

`nally/agent/harness.py::get_pipeline_config(task_class)` returns a
`PipelineConfig` with four boolean stages:

| Flag | Meaning |
|------|---------|
| `direct_answer` | Answer via the normal ReAct agent; no extra stages. |
| `critique` | Run generate→critique→revise after the agent responds. |
| `scratchpad` | Maintain a per-request `Scratchpad` working memory. |
| `tool_verify` | Verify each tool result against the task objective. |

**Defaults** (`DEFAULT_PIPELINES`):

| Class | direct_answer | critique | scratchpad | tool_verify |
|-------|---------------|----------|------------|-------------|
| SIMPLE | ✅ | ❌ | ❌ | ❌ |
| KNOWLEDGE | ✅ | ❌ | ❌ | ❌ |
| AMBIGUOUS | ✅ | ❌ | ❌ | ❌ |
| CREATIVE | ❌ | ✅ | ❌ | ❌ |
| COMPLEX | ❌ | ✅ | ✅ | ✅ |
| HIGH_STAKES | ❌ | ✅ | ✅ | ✅ |

The table is **overridable** per class via the `NALLY_HARNESS_PIPELINES` env var.
The reputation of these four stages is governed by the corresponding
`NALLY_HARNESS_*` master flags (see §7).

---

## 5. Phase 2 — Generate → Critique → Revise

`nally/agent/harness.py::run_critique_pipeline(user_request, task_class, llm_call_fn, context_messages=None)`

Fires for **CREATIVE** and **COMPLEX** classes. Runs three sub-steps:

1. **Generate** — produce a first answer via `llm_call_fn(messages, temperature=0.7)`.
2. **Critique** — a strict reviewer call (`temperature=0`) evaluates the draft against a
   **class-specific rubric** (`CRITIQUE_RUBRICS`) and returns JSON:
   `{"issues":[...], "severity":"none|low|medium|high", "should_revise":true|false}`.
3. **Revise** — if `should_revise` and severity ≠ `none`, a `temperature=0.3` editor call
   rewrites the draft fixing the issues (`stages_fired` includes `"revise"`).

- Max revision rounds per request: `1` (`_MAX_CRITIQUE_REVISIONS`).
- Result is a `CritiquePipelineResult` (`response`, `was_revised`, `critique`,
  `cost_tokens`, `cost_latency_ms`, `stages_fired`).
- Any sub-step failure degrades gracefully — the last good draft is returned and
  `was_revised=False`. The emit event `critique` carries `to_dict()` of the result to the UI.

**Rubrics** (class-specific — not generic "find problems"):

- `COMPLEX`: ACCURACY, COMPLETENESS, ORDERING, DEPENDENCIES, EDGE CASES, FEASIBILITY.
- `CREATIVE`: ORIGINALITY, COHERENCE, VOICE, DEPTH, COMPLETENESS, ENGAGEMENT.

---

## 6. Phase 3 — Scratchpad (per-request working memory)

`nally/agent/scratchpad.py`

A task-local, **ephemeral** object that persists across tool calls *within a single
request*. It is deliberately **separate from long-term memory** so task scratch state
never pollutes lasting knowledge.

`Scratchpad` fields (dataclass):

`objective`, `constraints[]`, `facts[]`, `assumptions[]`, `open_questions[]`,
`decisions[]`, `actions_taken[]`, `results[]`, `id`, `created_at`, `updated_at`, `status`.

Helper methods: `add_fact/add_assumption/add_open_question/add_decision/add_action/
add_result/add_constraint` (each stamps `updated_at`), `to_dict()`,
`to_context_string()` (compact LLM-injectable summary), and
`suggest_long_term_writes()`.

### Persistence — `ScratchpadStore`

- SQLite table `scratchpads` in **`data/nally_memory.db`** (WAL mode, busy_timeout 5s).
- Methods: `save` (upsert), `load(id)`, `load_active(thread_id)`, `complete(id)`,
  `fail(id)`, `cleanup(max_age_hours=24)`, `get_active_count()`.
- Module singleton: `scratchpad_store`.
- One row per task; completed/failed rows are deleted by `cleanup`.

### Write-back (deliberate, never automatic)

At end of task, the harness runs `suggest_long_term_writes()` and only then decides
what may persist to long-term memory. Suggested writes (capped at 10):
`task_fact:*` (category `auto_fact`), `task_decision:*` / `task_lesson:*` (category
`task`). Trivial entries (≤10 chars) are skipped. This write-back is an explicit
`memory_v2.remember(...)` call — never an automatic dump of the scratchpad.

---

## 7. Phase 4 — Tool-Result Verification

`nally/agent/harness.py::verify_tool_result(tool_name, tool_args, tool_result, tool_success, objective="")`

Before the harness treats a tool call as "done", it verifies the result:

1. **No hard error** — scans for traceback/error/exception/permission/filenotfound/
   value/type/key/index/runtime error tokens, plus the reported `tool_success`.
2. **Not empty/trivial** — empty, `None`, `null`, `ok`, `done` results are flagged.
3. **Addresses the objective** — keyword-overlap heuristic between the objective
   (from scratchpad/state) and the result text (stop-words removed; match-ratio gates).
4. **Evidence of completion** — completion signals like `successfully`, `created`,
   `installed`, `deployed`, `saved`, `written`, `completed` boost confidence.

Returns a `ToolVerification` (`action`, `result`, `evidence`, `satisfies_objective`,
`confidence`, `reasoning`). In the agent graph, failures emit a `tool_verification`
event to the UI. Hard retry cap: `NALLY_HARNESS_VERIFY_RETRIES` (default `2`).

---

## 8. Integration Points

| File | Where | What happens |
|------|-------|--------------|
| `nally/agent/core.py` ~L242 | start of turn | `classify_intent(user_input)`; creates a `Scratchpad` for COMPLEX/CREATIVE/HIGH_STAKES; stores `self._last_classification`. |
| `nally/agent/core.py` ~L414 | after agent run | For COMPLEX/CREATIVE, `run_critique_pipeline(...)`; if revised, replaces `final_response`; emits `critique` event. |
| `nally/agent/core.py` ~L469 | end of turn | Scratchpad write-back: complete the pad, `suggest_long_term_writes()` → `memory_v2.remember(...)`. |
| `nally/agent/graph.py` ~L1224 | after each tool call | `verify_tool_result(...)` when classify intent is COMPLEX/CREATIVE/HIGH_STAKES; login warns on low objective-match; emits `tool_verification`. |

The classification is also threaded into the ReAct graph as `intent_class` /
`intent_confidence` state so downstream stages know the task context.

---

## 9. Configuration

All Harness settings live in the `HARNESS_*` block of `nally/config.py`.

| Env var | Default | Effect |
|---------|---------|--------|
| `NALLY_HARNESS_ENABLED` | `false` | Master switch — turns on classification + all gated stages. |
| `NALLY_HARNESS_ROUTER` | `true` | Classification routing (active whenever the harness is enabled). |
| `NALLY_HARNESS_CRITIQUE` | `true` | Enables generate→critique→revise for CREATIVE/COMPLEX. |
| `NALLY_HARNESS_SCRATCHPAD` | `true` | Enables per-request scratchpad working memory. |
| `NALLY_HARNESS_VERIFY` | `true` | Enables tool-result verification. |
| `NALLY_HARNESS_LOG` | `true` | Logs each classification (`nally.harness` / intent log line). |
| `NALLY_HARNESS_PIPELINES` | `""` | JSON merge-override of per-class stage config, e.g. `'{"SIMPLE":{"critique":true}}'`. |
| `NALLY_HARNESS_VERIFY_RETRIES` | `2` | Hard retry cap for tool verification failures (read in `harness.py`). |

Example `.env`:
```env
NALLY_HARNESS_ENABLED=true
NALLY_HARNESS_CRITIQUE=true
NALLY_HARNESS_PIPELINES='{"SIMPLE":{"critique":true},"CREATIVE":{"tool_verify":true}}'
```

---

## 10. Evaluating the Harness

`tests/harness_eval/runner.py` runs classified test cases and reports pass rate,
class accuracy, and latency.

```bash
python -m tests.harness_eval.runner                      # run bundled cases
python -m tests.harness_eval.runner --cases path/to/cases --output results.json
```

- Cases live in `tests/harness_eval/cases/eval_cases.json` (13 cases covering
  SIMPLE/KNOWLEDGE/CREATIVE/COMPLEX/AMBIGUOUS/HIGH_STAKES plus injection and
  tool-failure edge cases — see sample above).
- `pass_criteria` handling is heuristic (keyword/class checks), intentionally not an
  LLM-as-judge in the offline runner.
- Injections must **not** classify as HIGH_STAKES (should be SIMPLE/AMBIGUOUS/
  KNOWLEDGE); tool-fail cases accept any classification.

Unit tests: `tests/test_harness.py` (regex classifier, LLM classifier, public API,
pipeline configs, critique pipeline, scratchpad + store, tool verification).

---

## 11. Troubleshooting

- **Nothing changes when I enable it?** Check `NALLY_HARNESS_ENABLED=true` is set.
  When disabled, all stages are inert and requests go straight to the ReAct agent.
- **Classification looks wrong** → it likely used the regex fallback (`method="regex"`).
  Provide an `llm_call_fn` or check the signals in §3. Log lines come from the
  `nally.harness` logger when `NALLY_HARNESS_LOG=true`.
- **Scratchpad rows linger** → run `scratchpad_store.cleanup()`; completed/failed
  pads are removed automatically on cleanup.
- **Critique never fires** → confirm the class is CREATIVE or COMPLEX, that
  `NALLY_HARNESS_CRITIQUE=true`, and that a com‑patible `llm_call_fn` is wired
  (`simple_chat` returns text; critique parsing needs valid JSON).