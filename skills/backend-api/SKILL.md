---
name: backend-api
description: Backend API development patterns: Express.js, PostgreSQL, JWT auth, Socket.IO, input validation, security. Use when building REST APIs, real-time features, or database-backed services.
allowed-tools: read_file file_ops run_command code_analysis
---

# Backend API

Patterns and best practices for building production-grade backend services.

## Phase 1: Project Setup

### Express Server Structure
```
server.js          — Entry point (middleware, routes, WebSocket)
config/
  db.js            — Database pool + query helper
  auth.js          — JWT config (REQUIRED, no fallbacks)
middleware/
  auth.js          — JWT verify + role authorize
  validate.js      — Input validation middleware
routes/
  auth.js          — Register, login, profile
  [resource].js    — CRUD endpoints
seeds/
  seed.js          — Idempotent seed data
```

### Environment Variables (Required)
```env
PORT=5000
DB_HOST=localhost
DB_PORT=5432
DB_NAME=myapp
DB_USER=postgres
DB_PASSWORD=secret
JWT_SECRET=generate-a-real-secret-here    # REQUIRED — throw on startup if missing
JWT_EXPIRES_IN=7d
FRONTEND_URL=http://localhost:3000
```

**Rule:** JWT_SECRET must be required. Throw on startup if not set:
```js
if (!process.env.JWT_SECRET) {
  console.error('FATAL: JWT_SECRET is not set');
  process.exit(1);
}
```

## Phase 2: Authentication

### Registration (Secure)
```js
// POST /api/auth/register
// DO NOT accept role from request body — prevent privilege escalation
router.post('/register', async (req, res) => {
  const { name, email, password } = req.body;  // NO role field

  // Validate required fields
  if (!name || !email || !password) {
    return res.status(400).json({ error: 'Name, email, and password are required.' });
  }

  // Validate email format
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return res.status(400).json({ error: 'Invalid email format.' });
  }

  // Validate password strength
  if (password.length < 8) {
    return res.status(400).json({ error: 'Password must be at least 8 characters.' });
  }

  // Check if user exists
  const existing = await query('SELECT id FROM users WHERE email = $1', [email]);
  if (existing.rows.length > 0) {
    return res.status(409).json({ error: 'Email already registered.' });
  }

  // Hash password
  const salt = await bcrypt.genSalt(10);
  const hashedPassword = await bcrypt.hash(password, salt);

  // Insert as viewer (default role) — admin role assigned separately
  const result = await query(
    'INSERT INTO users (name, email, password, role) VALUES ($1, $2, $3, $4) RETURNING id, name, email, role',
    [name, email, hashedPassword, 'viewer']
  );

  // Generate token
  const token = jwt.sign(
    { id: result.rows[0].id, email, role: 'viewer' },
    process.env.JWT_SECRET,
    { expiresIn: process.env.JWT_EXPIRES_IN || '7d' }
  );

  res.status(201).json({ user: result.rows[0], token });
});
```

### JWT Verification
```js
const authenticate = (req, res, next) => {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Access denied. No token provided.' });
  }

  const token = authHeader.split(' ')[1];
  try {
    const decoded = jwt.verify(token, process.env.JWT_SECRET, { algorithms: ['HS256'] });
    req.user = decoded;
    next();
  } catch (err) {
    return res.status(401).json({ error: 'Invalid or expired token.' });
  }
};

// Role-based authorization
const authorize = (...roles) => {
  return (req, res, next) => {
    if (!roles.includes(req.user.role)) {
      return res.status(403).json({ error: 'Insufficient permissions.' });
    }
    next();
  };
};
```

## Phase 3: Database

### PostgreSQL Pool Setup
```js
const { Pool } = require('pg');

const pool = new Pool({
  host: process.env.DB_HOST || 'localhost',
  port: process.env.DB_PORT || 5432,
  database: process.env.DB_NAME,
  user: process.env.DB_USER,
  password: process.env.DB_PASSWORD,
  max: 20,  // Connection pool size
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
});

// Throw on connection error (don't silently use defaults)
pool.on('error', (err) => {
  console.error('Database connection error:', err.message);
  process.exit(1);
});

const query = async (text, params) => {
  const start = Date.now();
  const result = await pool.query(text, params);
  const duration = Date.now() - start;
  if (duration > 1000) console.warn(`Slow query (${duration}ms):`, text.substring(0, 80));
  return result;
};

module.exports = { pool, query };
```

### Transactions (CRUD with Stock)
```js
const client = await pool.connect();
try {
  await client.query('BEGIN');

  // Validate and process
  for (const item of items) {
    const product = await client.query('SELECT stock FROM products WHERE id = $1', [item.product_id]);
    if (product.rows[0].stock < item.quantity) {
      await client.query('ROLLBACK');
      return res.status(400).json({ error: `Insufficient stock for product ${item.product_id}` });
    }
    await client.query('UPDATE products SET stock = stock - $1 WHERE id = $2', [item.quantity, item.product_id]);
  }

  // Create order
  const order = await client.query('INSERT INTO orders ... RETURNING *');
  await client.query('COMMIT');
  res.status(201).json(order.rows[0]);
} catch (err) {
  await client.query('ROLLBACK');
  throw err;
} finally {
  client.release();
}
```

### Idempotent Seeding
```js
// Use unique constraints + ON CONFLICT
await query(`
  CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,  -- UNIQUE constraint required
    price DECIMAL(10, 2) NOT NULL,
    stock INTEGER DEFAULT 0
  )
`);

// Seed with ON CONFLICT (works because of UNIQUE constraint)
await query(
  'INSERT INTO products (name, price, stock) VALUES ($1, $2, $3) ON CONFLICT (name) DO NOTHING',
  ['Product Name', 100, 50]
);
```

## Phase 4: Real-Time (Socket.IO)

### Server Setup
```js
const http = require('http');
const { Server } = require('socket.io');

const server = http.createServer(app);
const io = new Server(server, {
  cors: {
    origin: process.env.FRONTEND_URL || 'http://localhost:3000',
    methods: ['GET', 'POST'],
  },
});

// Make io accessible in routes
app.set('io', io);

io.on('connection', (socket) => {
  console.log('Client connected:', socket.id);

  socket.on('subscribe:orders', () => socket.join('orders'));
  socket.on('subscribe:alerts', () => socket.join('alerts'));

  socket.on('disconnect', () => console.log('Client disconnected:', socket.id));
});
```

### Emitting Events from Routes
```js
// After creating an order
const io = req.app.get('io');
if (io) {
  io.emit('order:created', order);
  io.to('alerts').emit('activity:new', { type: 'order', message: `New order #${order.id}` });
}
```

### Frontend Client (CRITICAL)
```html
<!-- MUST use socket.io-client, NOT native WebSocket -->
<script src="https://cdn.socket.io/4.7.4/socket.io.min.js"></script>
<script>
  const socket = io('http://localhost:5000');

  socket.on('connect', () => {
    socket.emit('subscribe:orders');
    socket.emit('subscribe:alerts');
  });

  socket.on('order:created', (order) => {
    // Update UI
  });

  socket.on('activity:new', (activity) => {
    // Update activity feed
  });
</script>
```

**NEVER use `new WebSocket()` with a Socket.IO server — they are incompatible protocols.**

## Phase 5: Input Validation

### Validate All Inputs
```js
// Before processing any request
const { name, price, stock } = req.body;

// Required fields
if (!name || !price) {
  return res.status(400).json({ error: 'Name and price are required.' });
}

// Type checks
if (typeof name !== 'string') {
  return res.status(400).json({ error: 'Name must be a string.' });
}

if (typeof price !== 'number' || price <= 0) {
  return res.status(400).json({ error: 'Price must be a positive number.' });
}

if (stock !== undefined && (typeof stock !== 'number' || stock < 0)) {
  return res.status(400).json({ error: 'Stock must be a non-negative number.' });
}

// Array validation
if (!Array.isArray(items) || items.length === 0) {
  return res.status(400).json({ error: 'Items must be a non-empty array.' });
}
```

### Financial Calculations
```js
// WRONG: SUM(price) ignores quantity
const revenue = await query('SELECT SUM(price) AS total FROM orders');

// CORRECT: Account for quantity
const revenue = await query('SELECT SUM(price * quantity) AS total FROM order_items');

// OR if items are stored as text summary, calculate per-item
let total = 0;
for (const item of items) {
  const product = await query('SELECT price FROM products WHERE id = $1', [item.product_id]);
  total += product.rows[0].price * item.quantity;
}
```

## Security Checklist

- [ ] JWT_SECRET required (throws on startup if missing)
- [ ] Registration does not accept role from request body
- [ ] All inputs validated (types, ranges, required fields)
- [ ] Rate limiting on auth endpoints (login, register)
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
| `SUM(price)` without quantity | Wrong revenue calculation | Include quantity in sum |
| `ON CONFLICT DO NOTHING` without unique constraint | Duplicates on re-seed | Add UNIQUE constraint |
| Placeholder comments in business logic | Features never implemented | Implement or remove |
| `JWT_SECRET` with fallback | Tokens signed with known secret | Require, throw if missing |
| No input validation | Bad data, crashes, injection | Validate all inputs |
| No `express.static()` | Frontend can't connect | Serve frontend from Express |
