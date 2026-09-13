# Skills

Skills provide specialized instructions and workflows for specific tasks. They use a two-level progressive disclosure system to balance context efficiency with capability.

## How Skills Work

### Level 1: Manifest (Always Active)

At startup, Nally scans `skills/*/SKILL.md`, extracts each skill's name and description (~100 tokens per skill), and injects them into the system prompt. This is cheap enough to include all skills.

### Level 2: Activation (On Demand)

When Nally identifies a matching skill for a user's request, it loads the full SKILL.md body into the current context. This provides detailed instructions only when needed.

## Skill Format

Each skill lives in `skills/<name>/SKILL.md` with YAML frontmatter + markdown body:

```markdown
---
name: my-skill
description: What this skill does and when to use it. Use for X, Y, Z tasks.
allowed-tools: read_file file_ops run_command
---

# My Skill

Detailed instructions for the agent...

## Phase 1: Do This
- Step one
- Step two

## Phase 2: Do That
...
```

### Frontmatter Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Skill name (hyphenated, e.g. `code-review`) |
| `description` | Yes | What it does — used for intent matching |
| `allowed-tools` | No | Tools this skill needs (overrides permission gate to `allow`) |

### Body Guidelines

- Write clear, actionable instructions for the agent
- Include phases/steps for complex workflows
- Specify output formats with examples
- Add anti-patterns and common mistakes
- Keep it focused — one skill = one domain

## Intent Matching

Nally matches skills to user messages using:

1. **Keyword overlap**: 3+ words from the skill description appear in the message
2. **Full name match**: All hyphenated parts of the skill name appear in the message (e.g. "ui-design" requires both "ui" AND "design")

Substring matching is intentionally avoided to prevent false positives (e.g. "ui" alone won't match `ui-design`).

## Security Validation

Before loading, each skill is checked for:

- **Prompt injection patterns**: "ignore previous instructions", "you are now", etc.
- **Suspicious URLs**: ngrok, webhook, requestbin, pipedream, hookbin
- **Env var reads**: Attempts to access environment variables

Skills with warnings are loaded but flagged in logs and `/api/skills`.

## Permission Rules

The `allowed-tools` field grants `allow` permission for those tools during skill execution. However:

- **Explicit `deny` in `permissions.json` cannot be overridden** — if a command is denied at the base level, skill overrides can't escalate past it
- Skill overrides only grant `allow`, never bypass `deny`

## Available Skills

| Skill | Purpose | Tools |
|-------|---------|-------|
| `api-design` | REST/GraphQL API review | read_file |
| `architect` | System design, migrations | read_file, file_ops, run_command, code_analysis |
| `backend-api` | Express.js, PostgreSQL, JWT | read_file, file_ops, run_command, code_analysis |
| `build` | Autonomous full-project engineering (build/scaffold/generate a project, system, app, CLI, tool, library) | engineering_build |
| `code-review` | Bug hunting, security audits | read_file, file_ops, run_command |
| `creative` | Business writing, marketing | web_search, read_file |
| `data` | Data analysis tasks | read_file |
| `design-system` | Design tokens, components | read_file, file_ops |
| `devops` | Docker, CI/CD, Terraform | run_command, file_ops |
| `diagnose` | Bug hunting + security audits | read_file, file_ops, run_command, code_analysis |
| `docs` | READMEs, API docs, tutorials | read_file, file_ops |
| `image-gen` | Image generation prompts | generate_image |
| `plan` | Task decomposition | (no tools — pure reasoning) |
| `productivity` | Regex, templates, explanations | read_file, file_ops, run_code |
| `refactor` | Code quality improvement | read_file, file_ops, run_command |
| `research` | Web research, synthesis | web_search, read_file |
| `ship` | Git workflow, deployment | run_command, file_ops |
| `test-writer` | Unit test generation | read_file, file_ops, run_command, run_code |
| `ui-design` | Layout, color, accessibility | read_file |
| `video-edit` | Higgsfield AI video editing | MCP Higgsfield tools |

## Creating a New Skill

1. Create a directory: `skills/my-skill/`
2. Create `SKILL.md` with frontmatter + body
3. Restart the server (or use hot-reload via `skill_registry.reload()`)
4. Test by asking Nally about the skill's topic

### Hot-Reload

Skills can be reloaded without restarting:

```python
from nally.skills.registry import skill_registry
skill_registry.reload()
```

## Self-Creation

Nally can create skills from successful workflows:

```python
skill_registry.create_skill(
    name="my-new-skill",
    description="What this skill does",
    body="# My New Skill\n\nInstructions..."
)
```

This creates the `SKILL.md` file and hot-reloads the registry.
