---
name: api-design
description: Use when the user needs API design review or guidance. Triggers on requests to design, review, or improve REST or GraphQL APIs. Checks naming conventions, versioning, pagination, error handling, authentication, and overall consistency.
allowed-tools:
  - read_file
---

## API Design Review

### Step 1: Identify API Type

1. Check if REST or GraphQL
2. Read existing endpoint definitions or schema files
3. Note the framework (Express, FastAPI, Flask, Gin, etc.)

### Step 2: Review REST Endpoints

For each endpoint, check:

**Naming Convention**
- Resources are nouns, not verbs: `/users`, not `/getUsers`
- Plural nouns: `/users`, not `/user`
- Nested resources max 2 levels: `/users/:id/orders`
- Use query params for filtering: `/users?role=admin`

**HTTP Methods**
- GET — read only, no side effects
- POST — create resource
- PUT — full replace
- PATCH — partial update
- DELETE — remove resource

**Versioning**
- URL prefix: `/api/v1/users`
- Or header: `Accept: application/vnd.api.v1+json`
- Version on breaking changes only

**Pagination**
- Offset-based: `?page=2&limit=20`
- Cursor-based (preferred for large datasets): `?cursor=abc123&limit=20`
- Response includes `total`, `hasMore`, `next_cursor`

**Error Handling**
- Consistent error shape:
  ```json
  {
    "error": {
      "code": "VALIDATION_ERROR",
      "message": "Email is required",
      "details": [{"field": "email", "issue": "missing"}]
    }
  }
  ```
- Use correct HTTP status codes: 400 (bad request), 401 (unauthorized), 403 (forbidden), 404 (not found), 409 (conflict), 422 (unprocessable), 429 (rate limited), 500 (server error)

**Auth Patterns**
- Bearer tokens in `Authorization` header
- API keys in `X-API-Key` header (not URL params)
- Rate limiting headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`

### Step 3: Review GraphQL Schema

1. Check type naming: PascalCase, singular (`User` not `Users`)
2. Check for `Node` interface for relay compatibility
3. Verify input types are separate from output types
4. Check pagination: `edges`/`cursor`/`pageInfo` pattern
5. Verify mutations return updated object, not just success

### Step 4: Output Review

```
## API Design Review

### Strengths
- Good: [specific praise]

### Issues Found
| Severity | Endpoint | Issue | Recommendation |
|----------|----------|-------|----------------|
| High | POST /user | Missing validation | Add request body validation |
| Med | GET /items | No pagination | Add cursor-based pagination |
| Low | /api/items | No versioning | Add /api/v1/ prefix |

### Recommendations
1. [Actionable recommendation with code example]
2. [Actionable recommendation]
```

## Design Principles

- Consistency over cleverness
- Predictable: if you know one endpoint, you can guess others
- HATEOAS: include links to related resources in responses
- Idempotency: PUT and DELETE should be safe to retry
- Backward compatibility: never remove fields, only add
