---
name: architect
description: System design, architecture decisions, migration planning, performance analysis, trade-off evaluation. Use for designing systems, planning migrations, optimizing bottlenecks, or making technical decisions.
allowed-tools: read_file file_ops run_command code_analysis
---

# Architect

High-level system design, migration, and performance decisions.

## Phase 1: Understand Requirements

Before designing anything:
- **Functional requirements** — what must it DO?
- **Non-functional requirements** — how must it PERFORM? (scale, latency, availability)
- **Constraints** — budget, team size, timeline, existing tech
- **Trade-offs** — what are we willing to sacrifice?

## Phase 2: System Design

### Architecture Patterns

**Monolith** — best for:
- Small teams (< 5 devs)
- MVP / early stage
- Simple domains
- Low traffic (< 10K RPS)

**Microservices** — best for:
- Large teams (independent deployments)
- Complex domains with clear boundaries
- Different scaling needs per service
- Polyglot tech requirements

**Serverless** — best for:
- Event-driven workloads
- Unpredictable traffic
- Rapid prototyping
- Low ops overhead

**Event-Driven** — best for:
- Async processing
- Decoupled services
- Audit trails
- Real-time updates

### Design Checklist
1. **Data flow** — how does a request move through the system?
2. **Data model** — what entities, relationships, access patterns?
3. **API surface** — REST, GraphQL, gRPC? Versioning strategy?
4. **Caching** — what to cache, where, invalidation strategy?
5. **Auth** — JWT, sessions, OAuth? Token refresh?
6. **Error handling** — retries, circuit breakers, dead letters?
7. **Observability** — logging, metrics, tracing?

### Diagram Description
```
[Client] → [API Gateway] → [Auth Service]
                           [User Service] → [User DB]
                           [Order Service] → [Order DB]
                           [Payment Service] → [Payment Gateway]
                           [Notification Service] → [Email/SMS Queue]
```

## Phase 3: Migration Planning

### Assess Current State
- What's the architecture today?
- What's working? What's broken?
- What's the pain point driving migration?
- What's the risk tolerance?

### Migration Strategies

**Strangler Fig** — best for:
- Large legacy systems
- Can't afford downtime
- Gradual migration
```
Old: [Legacy App] ← all traffic
Step 1: [Legacy] ← 90%, [New] ← 10%
Step 2: [Legacy] ← 50%, [New] ← 50%
Step 3: [Legacy] ← 10%, [New] ← 90%
Step 4: [New] ← all traffic
```

**Blue-Green** — best for:
- Zero-downtime deployments
- Quick rollback needed
- Database migration separate

**Database-First** — best for:
- Data model is the bottleneck
- Schema changes are complex
- Need to migrate data

### Migration Checklist
1. Data migration strategy (one-time vs continuous)
2. Rollback plan (what if it fails?)
3. Monitoring (how do we know it's working?)
4. Team training (who supports the new system?)

## Phase 4: Performance Analysis

### Find Bottlenecks
```
Request → [API] → [DB Query] → [External Service] → [Render]
              10ms    500ms          200ms              50ms
```

### Common Bottlenecks
| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Slow DB queries | Missing indexes, N+1 | Add indexes, batch queries |
| High memory | Leaks, large objects | Profile, fix leaks |
| Slow responses | External calls | Cache, async, timeout |
| Low throughput | Synchronous processing | Queue, parallelize |
| Timeouts | Downstream dependency | Circuit breaker, retry |

### Optimization Order
1. **Measure first** — don't guess
2. **Fix the biggest bottleneck** — not the easiest
3. **Measure again** — did it help?
4. **Repeat** until acceptable

## Phase 5: Decision Document

For each architectural decision:
- **Context** — what situation?
- **Decision** — what did we choose?
- **Alternatives** — what else was considered?
- **Consequences** — what trade-offs did we accept?
- **Rationale** — why this choice?

## Guidelines
- Design for today, accommodate tomorrow
- Simple beats clever — complexity is expensive
- Document decisions, not just code
- When unsure, ask "what's the cheapest way to validate this?"
