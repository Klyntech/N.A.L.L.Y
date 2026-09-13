# Milestone B — Full-Loop Computer Benchmark (Baseline)

**Date:** 2026-09-13
**Target:** Render-hosted NallPuter (`cmp_404356df` at `https://nallputer.onrender.com`)
**Provider:** OpenCode `muse-spark-1.3-contributor-free`
**Budget:** NALLY defaults (SIMPLE 120s / COMPLEX 600s wall, 50 tool calls, 5 failures)

---

## Results

| # | Task | Category | Intent | Result | Wall (s) | Budget % |
|---|------|----------|--------|--------|----------|----------|
| u01 | Single file write | stc | SIMPLE | **PASS** | 28 | 47% |
| u02 | Write + read back | mtc | COMPLEX | **PASS** | 76 | 85% |
| u03 | 3-file chain + sum | mcp | COMPLEX | **PASS** | 160 | 133% |
| u04 | Observation chain (3-step) | mcp | COMPLEX | **PASS** | 170 | 142% |
| u05 | Write script + exec | plan | COMPLEX | **PASS** | 78 | 65% |
| u06 | Persistence write | persist | SIMPLE | **PASS** | 16 | 27% |
| u06b | Persistence read | persist | SIMPLE | **PASS** | 17 | 29% |
| u07 | Self-correction | recovery | SIMPLE | **PASS** | 24 | 27% |
| u08 | Remote exec command | stc | SIMPLE | **PASS** | 48 | 80% |

**Score: 9/9 PASS (100%)**

---

## Key findings

### 1. NALLY completes multi-step computer tasks

All 9 tasks passed. NALLY can:
- Write files to a remote Render computer
- Read files back and use observations to drive next actions
- Plan multi-step sequences (3-file chain, observation chain)
- Write and execute scripts on the remote computer
- Self-correct when given wrong instructions
- Persist state across sessions

### 2. Budget overrun on COMPLEX tasks

2 tasks exceeded 100% wall-clock budget:
- **u03** (3-file chain): 133% — planning + critique pipeline added latency
- **u04** (observation chain): 142% — 3-step chain with critique revision

The budget overrun didn't prevent completion — the tasks still passed. But it means COMPLEX tasks on Render need either higher budgets or faster execution.

### 3. Claim-vs-reality mismatch (critical finding)

**u03 response:** "I haven't been able to write or read those files from this session — I don't have filesystem tool access"

**u03 filesystem truth:** All 3 files written with correct content (10, 20, 30). 6/6 verification checks PASS.

The critique pipeline's LLM output contradicted the tool receipts. The verification layer didn't catch this because the critique runs its own internal LLM call that bypasses the verification gate.

This is a **real verification layer gap** — the benchmark successfully surfaced it.

### 4. Render cold-start latency

Each task adds ~15-30s warm-up overhead on Render free tier. Total benchmark wall time: ~10.3 minutes for 9 tasks.

---

## What this proves

> **NALLY can autonomously accomplish meaningful multi-step computer tasks using its real Render-hosted computer.** The full loop — objective → plan/react → NallPuter operations → observation → verification → completion — works end-to-end.

The claim-vs-reality mismatch on u03 is the first concrete bottleneck the benchmark surfaced. It should be classified in Milestone D as either a NALLY verification gap or an architectural issue.

---

## Task matrix

| Category | Count | Description |
|----------|-------|-------------|
| stc | 2 | Single tool call (write, exec) |
| mtc | 1 | Multi-tool chain (write → read) |
| mcp | 2 | Multi-step with planning (3-file chain, observation chain) |
| plan | 1 | Write script + execute + capture output |
| persist | 2 | Cross-session file persistence |
| recovery | 1 | Self-correction on wrong filename |
| **Total** | **9** | |

---

## Baseline artifact

```
tests/eval/suite_u/results/render_20260913_180414.json
```
