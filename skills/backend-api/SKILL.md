---
name: backend-api
description: Backend API development patterns: Express.js, PostgreSQL, JWT auth, Socket.IO, input validation, security. Use when building REST APIs, real-time features, or database-backed services.
allowed-tools: read_file file_ops run_command code_analysis
---

# Backend API

Patterns for production-grade backend services.

## Phase 1: Project Setup

```
server.js          — Entry point (middleware, routes, WebSocket)
config/db.js       — Database pool + query helper
config/auth.js     — JWT config (REQUIRED, no fallbacks)
middleware/auth.js  — JWT verify + role authorize
middleware/validate.js — Input validation
routes/auth.js     — Register, login, profile
routes/[resource].js — CRUD endpoints
seeds/seed.js      — Idempotent seed data
```

### Environment Variables (Required)
```env
PORT=5000
DB_HOST=localhost DB_PORT=5432 DB_NAME=myapp DB_USER=postgres DB_PASSWORD=secret
JWT_SECRET=generate-a-real-secret-here    # REQUIRED — throw on startup if missing
JWT_EXPIRES_IN=7d
FRONTEND_URL=http://localhost:3000
```

**Rule:** JWT_SECRET must be required. Throw on startup if not set.

## Phase 2: Authentication

### Registration
- DO NOT accept `role` from request body — prevent privilege escalation
- Validate required fields, email format, password strength (>= 8 chars)
- Check for existing user before insert
- Hash password with bcrypt (salt rounds >= 10)
- Assign default role server-side (e.g. `viewer`)

### JWT Verification
- Extract token from `Authorization: Bearer <token>` header
- Verify with `jwt.verify(token, secret, { algorithms: ['HS256'] })`
- Attach decoded payload to `req.user`
- Role-based auth: check `req.user.role` against allowed roles

## Phase 3: Database

### PostgreSQL Pool
- Use connection pooling (max: 20, idle timeout: 30s)
- Log slow queries (> 1s)
- Throw on connection error (don't silently use defaults)

### Transactions
- Use `BEGIN`/`COMMIT`/`ROLLBACK` for multi-step operations
- Validate before commit (e.g. check stock before deducting)
- Always `client.release()` in `finally` block

### Idempotent Seeding
- Use `CREATE TABLE IF NOT EXISTS` with `UNIQUE` constraints
- Seed with `ON CONFLICT (name) DO NOTHING`

## Phase 4: Real-Time (Socket.IO)

- Use `socket.io-client` on frontend — NEVER native `new WebSocket()` (incompatible protocols)
- Set up rooms for subscriptions: `socket.join('orders')`
- Emit from routes via `req.app.get('io')`
- CORS must match actual frontend origin

## Phase 5: Input Validation

- Validate ALL inputs: required fields, types, ranges, formats
- Type checks: string, number, boolean, array
- Range checks: price > 0, stock >= 0, array.length > 0
- Financial calculations: always include quantity (`SUM(price * quantity)`, not `SUM(price)`)

## Security Checklist

- [ ] JWT_SECRET required (throws on startup if missing)
- [ ] Registration does not accept role from request body
- [ ] All inputs validated (types, ranges, required fields)
- [ ] Rate limiting on auth endpoints
- [ ] CORS configured for actual frontend origin
- [ ] No hardcoded secrets or passwords
- [ ] Error handlers don't leak stack traces in production
- [ ] SQL uses parameterized queries (no string concatenation)
- [ ] bcrypt for password hashing (salt rounds >= 10)
- [ ] JWT specifies `algorithms: ['HS256']` to prevent algorithm switching

## Common Anti-Patterns

| Anti-Pattern | Problem | Fix |
|-------------|---------|-----|
| `new WebSocket()` with Socket.IO | Incompatible protocols | Use `socket.io-client` |
| `role` in registration body | Privilege escalation | Assign role server-side |
| `SUM(price)` without quantity | Wrong revenue | Include quantity in sum |
| `ON CONFLICT DO NOTHING` without UNIQUE | Duplicates on re-seed | Add UNIQUE constraint |
| `JWT_SECRET` with fallback | Known-secret tokens | Require, throw if missing |
| No input validation | Bad data, crashes, injection | Validate all inputs |
