---
name: plan
description: Use when the user needs a complex task broken into actionable steps. Triggers on requests to plan, strategize, create a roadmap, organize work, or break down a project. Produces ordered steps with dependencies, estimates, and risk assessment.
allowed-tools: []
---

## Planning Workflow

### Step 1: Understand the Goal

1. Restate the objective in one sentence
2. Identify the definition of done — what does success look like
3. Note any constraints: deadline, budget, technology, team size
4. Identify known unknowns — what needs to be researched first

### Step 2: Decompose the Work

1. Break the goal into major phases (3-7 typically)
2. Break each phase into concrete tasks (2-6 per phase)
3. Each task should be:
   - Completable in one sitting (1-4 hours ideally)
   - Independently verifiable (has a clear "done" state)
   - Owned by one person (no ambiguous responsibility)

### Step 3: Determine Dependencies

For each task, identify:
- **Prerequisites** — what must be done first
- **Blocks** — what this task prevents from starting
- **Parallelizable** — what can happen at the same time

Order tasks so dependencies flow downward:
```
Phase 1: Research (no dependencies)
  └── Phase 2: Design (depends on Phase 1)
       └── Phase 3: Implement (depends on Phase 2)
            └── Phase 4: Test (depends on Phase 3)
```

### Step 4: Estimate Each Task

Use t-shirt sizing:
- **XS** (< 1 hour) — config change, typo fix, simple addition
- **S** (1-4 hours) — single function, small component
- **M** (4-12 hours) — feature, integration, multiple files
- **L** (1-3 days) — subsystem, major refactor, new module
- **XL** (3+ days) — break into smaller tasks

### Step 5: Identify Risks

For each phase, note:
- **Risk** — what could go wrong
- **Probability** — low / medium / high
- **Impact** — low / medium / high
- **Mitigation** — how to reduce or handle it

Common risks:
- External dependency unavailable
- Scope creep (features expanding)
- Integration complexity underestimated
- Missing expertise in team

### Step 6: Output Format

```
## Plan: [Objective]

### Overview
**Goal:** [one sentence]
**Done when:** [definition of success]
**Timeline:** [estimated duration]
**Constraints:** [known limitations]

### Phase 1: [Name]
**Duration:** [estimate]
**Depends on:** nothing

| # | Task | Size | Owner | Risk |
|---|------|------|-------|------|
| 1.1 | [Specific task] | S | [person] | Low |
| 1.2 | [Specific task] | M | [person] | Med |

### Phase 2: [Name]
**Duration:** [estimate]
**Depends on:** Phase 1

| # | Task | Size | Owner | Risk |
|---|------|------|-------|------|
| 2.1 | [Specific task] | M | [person] | Low |

### Dependencies Graph
1.1 → 2.1 → 3.1
1.2 → 2.2
     2.3 → 3.2

### Risks
| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| [Risk 1] | Med | High | [Action] |

### Parallel Opportunities
- Tasks 1.1 and 1.2 can run simultaneously
- Tasks 2.2 and 2.3 can run simultaneously

### Milestones
- [ ] End of Phase 1: [checkpoint]
- [ ] End of Phase 2: [checkpoint]
- [ ] Final delivery: [date]
```

## Planning Principles

- Start with the end state, work backward
- Make tasks small enough to estimate accurately
- Front-load research and design before implementation
- Build in buffer for unknowns (add 20-30% to estimates)
- Identify the critical path — longest dependency chain
- Prefer parallel work where possible
- Include a "verification" step after each major phase
