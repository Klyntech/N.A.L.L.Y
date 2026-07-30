---
name: code-review
description: Review code for bugs, security issues, style violations, and logic errors. Use when asked to review code, check a PR, audit code quality, or find issues.
allowed-tools: read_file file_ops run_command
---

# Code Review

## Methodology

### 1. Understand the Scope
- What files changed? What's the intent?
- Read the full file, not just the diff — context matters

### 2. Check for Bugs First (Critical)
- Off-by-one errors in loops/arrays
- Null/undefined handling — what happens when input is missing?
- Race conditions in async code
- Resource leaks (unclosed connections, file handles, memory)
- Exception swallowing — empty catch blocks that hide real errors
- Type mismatches between function signatures and callers

### 3. Check Security (Critical)
- Injection vulnerabilities (SQL, XSS, command injection)
- Hardcoded secrets, API keys, tokens
- Missing input validation on user-facing endpoints
- Auth bypass potential — does every route check permissions?
- Data exposure — are sensitive fields logged or returned?

### 4. Check Logic (Warning)
- Dead code — unreachable branches, unused variables
- Duplicate logic that should be extracted
- Incorrect algorithm choice (O(n²) where O(n) exists)
- Missing edge cases (empty lists, zero values, unicode)
- Inconsistent error handling patterns

### 5. Check Style (Info)
- Naming clarity — does the name describe what it does?
- Function length — if it's >50 lines, it's doing too much
- Comment quality — comments explain WHY, not WHAT
- Import organization

## Output Format

For each finding, report:
- **File:line** — where the issue is
- **Severity** — critical / warning / info
- **What** — the specific problem
- **Why** — why it matters
- **Fix** — how to fix it (if applicable)

Group by severity. Critical first.

## Guidelines
- Focus on logic and security over style
- Don't nitpick formatting — that's what linters are for
- If code is good, say so briefly — don't invent issues
- When unsure if something is a bug, flag it as "potential" with explanation
