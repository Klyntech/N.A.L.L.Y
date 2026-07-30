---
name: diagnose
description: Combined bug hunting and security auditing. Find root causes, trace errors, identify vulnerabilities, and assess risk. Use when something is broken, throwing errors, or needs a security review.
allowed-tools: read_file file_ops run_command code_analysis
---

# Diagnose

A unified skill for finding bugs AND security issues in one pass.

## Phase 1: Understand the Problem

- What's the error message? Copy it exactly.
- When does it happen? Every time, intermittently, or only under load?
- What changed recently? Check git log, file timestamps.
- Can you reproduce it? What are the exact steps?

## Phase 2: Bug Hunting

### Read the Error
- Parse the stack trace — answer is usually in first 3 frames
- What line caused it? Go there.
- What was the state? Check variables at that point.

### Binary Search
- Comment out half — does bug persist? Narrow down.
- Add logging at key points — trace data flow.
- Use `git bisect` for recent regressions.

### Root Cause (Not Symptom)
Common root causes:
- Wrong data type (string where int expected)
- Missing null check
- Stale state (cached value that should have updated)
- Race condition (two things modifying same state)
- Wrong assumption about API behavior
- Off-by-one in loops/arrays
- Exception swallowing (empty catch blocks)

## Phase 3: Security Audit

Run these checks alongside bug hunting:

### OWASP Top 10
- **Injection**: SQL, XSS, command injection — is user input sanitized?
- **Broken Auth**: Are all routes checking permissions? Token validation?
- **Sensitive Data Exposure**: Are secrets logged? Returned in responses?
- **XXE**: XML parsing without disabling external entities?
- **Broken Access Control**: Can user A access user B's data?
- **Security Misconfiguration**: Debug mode on? Default credentials?
- **XSS**: Is user input rendered as HTML without escaping?

### Quick Security Scan
```
grep -rn "password\|secret\|token\|api_key" --include="*.py" --include="*.js" .
grep -rn "eval\|exec\|subprocess\|os\.system" --include="*.py" .
grep -rn "innerHTML\|document\.write\|v-html" --include="*.js" --include="*.vue" .
```

### Auth & Secrets
- Hardcoded secrets in code? (critical)
- Tokens in URLs instead of headers?
- Missing rate limiting on auth endpoints?
- JWT without expiration?
- CORS too permissive?

## Phase 4: Output

For each finding, report:
- **File:line** — where
- **Type** — bug / security / performance
- **Severity** — critical / warning / info
- **What** — the specific problem
- **Why** — why it matters
- **Fix** — how to fix it

## Guidelines
- Bugs first, then security — prioritize what's broken
- Don't guess at fixes — trace data flow
- When unsure, flag as "potential" with explanation
- If code is good, say so — don't invent issues
