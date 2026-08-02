---
name: productivity
description: Quick helpers: build regex patterns, explain concepts at any level, generate boilerplate/template code. Use when you need a regex, want something explained, or need project scaffolding.
allowed-tools: read_file file_ops run_code
---

# Productivity

Quick helper skills: regex, templates, explanations.

## Regex Builder

### How to Build Regex

**Start simple, add complexity:**
1. Write the simplest pattern that matches
2. Test it against all known cases
3. Add edge cases one at a time

**Common Patterns:**
```python
# Email (simplified)
r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

# Phone (US)
r"^\+?1?\d{10,14}$"

# URL
r"^https?://[^\s/$.?#].[^\s]*$"

# IP Address (v4)
r"^(\d{1,3}\.){3}\d{1,3}$"

# Date (YYYY-MM-DD)
r"^\d{4}-\d{2}-\d{2}$"

# Hex Color
r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$"

# Slug
r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
```

**Anchors & Quantifiers:**
```
^       start of string
$       end of string
\d      digit
\w      word character (letter, digit, underscore)
\s      whitespace
.       any character (except newline)
*       0 or more
+       1 or more
?       0 or 1 (also makes quantifier lazy)
{n}     exactly n
{n,m}   between n and m
```

**Groups & Lookaround:**
```
(abc)       capturing group
(?:abc)     non-capturing group
(?P<name>)  named group
(?=abc)     positive lookahead
(?!abc)     negative lookahead
(?<=abc)    positive lookbehind
(?<!abc)    negative lookbehind
```

### Test Your Regex
```python
import re

pattern = r"^\d{3}-\d{4}$"
test_cases = ["123-4567", "12-3456", "1234-567", "abc-defg"]

for test in test_cases:
    match = re.fullmatch(pattern, test)
    print(f"{test}: {'✓' if match else '✗'}")
```

## Concept Explainer

### Levels

**Level 1: Beginner**
- What is it? (one sentence)
- Why does it exist? (problem it solves)
- Simple analogy
- Basic example

**Level 2: Intermediate**
- How does it work under the hood?
- When should you use it?
- Common patterns
- Trade-offs vs alternatives

**Level 3: Advanced**
- Edge cases and gotchas
- Performance implications
- Source code / internals
- Advanced patterns

### Explanation Template
```markdown
## [Concept]

**In one sentence:** [What it is]

**Analogy:** [Real-world comparison]

**Problem it solves:** [Why we need it]

**How it works:**
1. [Step 1]
2. [Step 2]
3. [Step 3]

**Example:**
[code example]

**When to use:**
- [Use case 1]
- [Use case 2]

**When NOT to use:**
- [Anti-pattern 1]
- [Anti-pattern 2]
```

## Template Generator

### Project Scaffolding

**Python API (FastAPI):**
```
project/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── models/
│   ├── routes/
│   └── services/
├── tests/
├── requirements.txt
├── .env.example
├── Dockerfile
└── README.md
```

**React App:**
```
src/
├── components/
│   └── [Name]/
│       ├── [Name].tsx
│       ├── [Name].module.css
│       └── [Name].test.tsx
├── hooks/
├── services/
├── types/
└── utils/
```

**Node.js API (Express):**
```
project/
├── src/
│   ├── controllers/
│   ├── middleware/
│   ├── models/
│   ├── routes/
│   └── utils/
├── tests/
├── package.json
├── .eslintrc
└── Dockerfile
```

### Config Templates

**.env.example:**
```env
# App
NODE_ENV=development
PORT=5000

# Database
DATABASE_URL=sqlite:///data/app.db

# Auth
JWT_SECRET=change-me-in-production

# External Services
API_KEY=your-key-here
```

**package.json (minimal):**
```json
{
  "name": "my-app",
  "version": "1.0.0",
  "scripts": {
    "dev": "nodemon src/index.js",
    "start": "node src/index.js",
    "test": "jest",
    "lint": "eslint src/"
  }
}
```

## Guidelines
- For regex: test against edge cases, not just happy path
- For explanations: match the audience's level
- For templates: follow project conventions
- When unsure, ask what level/detail is needed
