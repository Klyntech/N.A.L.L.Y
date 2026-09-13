# NallPuter Contract — `nally/computer/`

Provider-neutral contract between the agent and a remote computer
(NallPuter `openapi.yaml` v0.1 + integration note `009`).
Source of truth is code: `nally/computer/{models,client,preflight,orchestrator,reconnect,adapter}.py`.

## Chain

```
ToolRegistry → ComputerAdapter → NallPuterClient → (transport)
```

- `ToolRegistry` never becomes the client; transport never leaks into tools.
- The adapter owns: **which** computer, **is it ready**, **what can it do**,
  exec orchestration, reconnect loop, lifecycle (start/stop/destroy), sync,
  workspace file ops.
- The adapter does **not** own: routing, planning, ReAct, tool execution.

## Slices

| Slice | Module | Responsibility |
|-------|--------|----------------|
| 1 — Contract | `models.py` | Python-native dataclasses mirroring the OpenAPI surface: `MachineProfile`, `Health`, `Computer`, `SyncState`, `ComputerError`. No provider branching, no transport. |
| 1 — Transport | `client.py` | `ComputerClient` — raw API calls only. |
| 1 — Readiness | `preflight.py` | `run_preflight()` + `CachedPreflight` — identity, health, capability surface before any exec. |
| 2 — Execution | `orchestrator.py` | `exec_orchestrator(ExecRequest) → RunResult` — bounded execution (resources, wall-time, output caps). |
| 3 — Lifecycle | `reconnect.py` | `reconnect()`, `start/stop/destroy_computer()`, `force_sync()`, uptime-reset detection with cache invalidation. |
| 4 — Boundary | `adapter.py` | `ComputerAdapter` — the only agent-facing surface. `preflight()`, `describe()` (branch on capabilities, never provider), `invalidate()` on machine mismatch. |

## Core types

- `MachineProfile` — identity + `Persistence` (instance / workspace / packages / snapshots) + `Resources` (cpu, memory, disk, pids, wall-time, output caps) + `Capabilities` (shell, files, package-install, network with **deny-by-default egress**).
- `Health` — `status: ok | degraded | recovering` + uptime.
- `SyncState` — `synced | pending | degraded | env_replay_failed`.
- `ComputerState` — `creating → running → idle → stopping → stopped`, plus `starting / error / recovering / destroying / destroyed`.
- `ComputerError` — typed failure with a `details` field (never a bare string).

## Invariants

1. **Preflight before exec** — `describe()` reports `ready: false` until a successful preflight; callers branch on the description, never on provider strings.
2. **Cache invalidation** — uptime reset or machine mismatch calls `adapter.invalidate()`; stale profiles are never reused.
3. **Bounded by default** — every exec carries resource limits (500 millicores / 512 MB / 300 s wall-time defaults); output is capped, never streamed unbounded.
4. **Deny-by-default egress** — network capability is explicit; no implicit outbound access.
5. **Restart behavior** — `instance_recreated`; persistence is reconstructible, not assumed. Ephemeral vs. persistent paths are declared on the profile.

## Related

- Full-loop benchmark baseline (9/9 PASS): `tests/eval/suite_u/REPORT.md`
- Tool-side wiring: `nally/tools/registry.py` (`set_computer_adapter`)
- Architecture overview: `ARCHITECTURE.md`
