---
name: docs
description: Generate documentation from code: READMEs, API docs, inline comments, changelogs, tutorials, learning guides. Use when writing docs for code or creating educational content.
allowed-tools: read_file file_ops
---

# Docs

Generate documentation and learning content from code.

## Phase 1: Understand the Code

- What does this project/module/function do?
- Who is the audience? (developers, users, beginners)
- What level of detail is needed?
- What's the existing docs situation?

## Phase 2: Choose Doc Type

### README.md
Essential sections:
1. **What** — one-line description
2. **Why** — problem it solves
3. **Quick Start** — 3 commands to get running
4. **Install** — dependencies, setup steps
5. **Usage** — common commands/APIs with examples
6. **Configuration** — env vars, config files
7. **Contributing** — how to add features/fix bugs
8. **License** — MIT, Apache, etc.

### API Documentation
For each endpoint/function:
- **Name** — what it does
- **Input** — parameters, types, defaults
- **Output** — return type, structure
- **Errors** — what can go wrong
- **Example** — curl call or code snippet

```markdown
## POST /api/users

Create a new user account.

**Request:**
\```json
{
  "name": "Clinton",
  "email": "clinton@example.com"
}
\```

**Response (201):**
\```json
{
  "id": "usr_123",
  "name": "Clinton",
  "email": "clinton@example.com",
  "created_at": "2026-01-15T10:30:00Z"
}
\```

**Errors:**
- 400: Missing required fields
- 409: Email already exists
```

### Inline Comments
Comment WHY, not WHAT:
```python
# Bad: increments counter by 1
counter += 1

# Good: retry failed requests up to 3 times
for attempt in range(MAX_RETRIES):
    counter += 1
```

### Changelog
Follow Keep a Changelog format:
```markdown
# Changelog

## [1.2.0] - 2026-01-15
### Added
- OAuth2 login flow
- Rate limiting on API endpoints

### Fixed
- Null pointer in user search
- Memory leak in WebSocket handler

### Removed
- Deprecated /v1/ endpoints
```

### Tutorial (Learning Guide)
Structure:
1. **Prerequisites** — what they need to know
2. **Setup** — create project, install deps
3. **Step 1** — simplest possible version
4. **Step 2** — add complexity
5. **Step 3** — add real-world features
6. **Next Steps** — where to go from here

Each step:
- Goal: what they'll learn
- Code: copy-pasteable, with line numbers
- Explanation: what each part does
- Checkpoint: how to verify it works

## Phase 3: Write

### Style Rules
- Use active voice: "The function returns..." not "The value is returned..."
- Be specific: "Returns a list of User objects" not "Returns data"
- Include code examples for every concept
- Use tables for structured info (params, options, etc.)
- Keep paragraphs short (3-4 sentences max)

### Code Examples
- Always include imports
- Show expected output in comments
- Handle errors in examples (don't show happy path only)
- Use realistic variable names, not `foo`/`bar`

## Guidelines
- Match the docs to the audience — beginner docs shouldn't assume knowledge
- If the code is complex, add a diagram (ASCII or description)
- When updating code, always check if docs need updating too
- Dead docs are worse than no docs — keep them accurate
