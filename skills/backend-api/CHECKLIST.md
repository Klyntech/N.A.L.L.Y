# Backend Pre-Deployment Checklist

Run this checklist before deploying any backend service.

## Security

- [ ] JWT_SECRET is required (throws on startup if missing)
- [ ] Registration endpoint does NOT accept role from request body
- [ ] All API inputs validated (required fields, types, ranges)
- [ ] Rate limiting on auth endpoints (login, register)
- [ ] CORS configured for actual frontend origin (not wildcard)
- [ ] No hardcoded secrets or passwords in code
- [ ] Error handlers don't leak stack traces in production
- [ ] SQL uses parameterized queries (no string concatenation)
- [ ] bcrypt for password hashing (salt rounds >= 10)
- [ ] JWT specifies `algorithms: ['HS256']` explicitly

## Architecture

- [ ] Express includes `express.static()` to serve frontend files
- [ ] Database connection pool configured (max connections, timeouts)
- [ ] WebSocket uses Socket.IO server + socket.io-client (not native WebSocket)
- [ ] Routes separated from server.js (modular structure)
- [ ] Middleware for auth, validation, error handling

## Data Integrity

- [ ] Seed data uses unique constraints (prevents duplicates on re-seed)
- [ ] Financial calculations account for quantity (not just price)
- [ ] Transactions used for multi-step operations (BEGIN/COMMIT/ROLLBACK)
- [ ] No placeholder comments in business logic (implement or remove)
- [ ] All database queries use parameterized inputs

## Real-Time

- [ ] Socket.IO client used on frontend (CDN or npm)
- [ ] WebSocket connections authenticated (or restricted by CORS)
- [ ] Events emitted for all state changes (create, update, delete)
- [ ] Room subscriptions for targeted updates (orders, alerts)

## Operations

- [ ] Health check endpoint (`GET /api/health`)
- [ ] Graceful shutdown handling (close DB pool, WebSocket server)
- [ ] Logging for errors and slow queries
- [ ] Environment variables documented in .env.example
- [ ] README covers all endpoints, setup, and WebSocket client usage
