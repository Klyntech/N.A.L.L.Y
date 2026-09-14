---
name: data
description: Data cleaning, SQL optimization, CSV/Excel processing. Handle nulls, deduplicate, normalize, fix schemas, optimize queries. Use when working with databases, CSVs, or data pipelines.
allowed-tools: read_file file_ops run_command code_analysis
---

# Data

Unified skill for data work: cleaning, transformation, SQL optimization.

## Phase 1: Assess the Data

### For CSVs/Files
- How many rows? What columns?
- What types? (string, int, date, etc.)
- Any nulls, empty strings, or placeholders like "N/A", "-", "null"?
- Duplicates? How many?
- Consistent formatting? (dates, phone numbers, addresses)

### For SQL/Database
- What's the schema? `SHOW CREATE TABLE` or `\d table_name`
- How many rows in each table?
- What indexes exist? `SHOW INDEX FROM table_name`
- Any foreign keys? What's the relationship?

## Phase 2: Clean (CSV/Files)

### Common Cleaning Steps
```python
import pandas as pd

df = pd.read_csv('data.csv')

# 1. Drop fully empty rows
df = df.dropna(how='all')

# 2. Fill nulls appropriately
df['name'] = df['name'].fillna('Unknown')
df['amount'] = df['amount'].fillna(0)
df['date'] = df['date'].ffill()  # forward fill

# 3. Strip whitespace
df = df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)

# 4. Normalize text
df['email'] = df['email'].str.lower()

# 5. Parse dates consistently
df['date'] = pd.to_datetime(df['date'], errors='coerce')

# 6. Remove duplicates
df = df.drop_duplicates()

# 7. Fix types
df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
```

### Validate After Cleaning
- Row count: how many removed? Is that expected?
- Null count per column: should be 0 or acceptable
- Types correct? Dates parse, numbers are numeric
- No duplicate primary keys

## Phase 3: Optimize (SQL)

### Find Slow Queries
```sql
-- Enable query logging
SET log_min_duration_statement = 1000;  -- log queries > 1s

-- Check query plan
EXPLAIN ANALYZE SELECT ...;
```

### Common Fixes

**N+1 Query**
```sql
-- Bad: runs once per row
SELECT * FROM orders WHERE user_id = ?;
-- × 100 users = 101 queries

-- Good: single query
SELECT * FROM orders WHERE user_id IN (SELECT id FROM users WHERE active = true);
```

**Missing Index**
```sql
-- Slow: full table scan
SELECT * FROM orders WHERE user_id = 123;

-- Add index
CREATE INDEX idx_orders_user_id ON orders(user_id);
```

**SELECT ***
```sql
-- Bad: fetches everything
SELECT * FROM users;

-- Good: fetch only what you need
SELECT id, name, email FROM users;
```

**N+1 in ORMs**
```python
# Bad
for user in users:
    orders = db.query("SELECT * FROM orders WHERE user_id = ?", user.id)

# Good
user_ids = [u.id for u in users]
orders = db.query("SELECT * FROM orders WHERE user_id IN ?", user_ids)
```

### Index Strategy
- Index columns used in WHERE, JOIN, ORDER BY
- Don't over-index (slows writes)
- Composite index: most selective column first
- Use EXPLAIN to verify index usage

## Phase 4: Output

- What was wrong: summarize issues found
- What was fixed: list all changes
- Before/after: row counts, query times, data quality metrics
- Prevention: how to avoid this in future (validation, constraints)

## Guidelines
- Always backup before cleaning
- Show before/after stats
- Explain WHY each cleaning step is needed
- For large datasets, sample first — don't load 1M rows to test
