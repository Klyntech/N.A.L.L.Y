# Skills

Nally's repository contains reusable skill documents under `skills/<name>/SKILL.md`. They describe domain-specific workflows and can be inspected through the skill catalog endpoints in the web UI.

## Current runtime behavior

The simplified core agent does **not** classify every request against skill descriptions, automatically inject a skill manifest into the system prompt, or activate a matching skill before the main model call. Skills are reference documents at present, not a separate reasoning or routing layer.

The `allowed-tools` frontmatter found in older skill files is not a source of tool availability or permission grants for the core agent. The active tool schemas come from the fixed registry in `nally/tools/__init__.py`; permission decisions come from `nally/config/permissions.json` and the permission gate.

## Skill format

A skill document may use YAML frontmatter and a Markdown body:

```markdown
---
name: my-skill
description: What the workflow covers and when it is relevant
---

# My Skill

Explain the workflow, constraints, expected outputs, and common mistakes.
```

Keep each skill focused, actionable, and consistent with the actual tools in the core registry. Do not assume a tool mentioned in a skill exists or is callable.

## Available reference documents

| Skill | Purpose |
|---|---|
| `api-design` | REST and GraphQL API review |
| `architect` | System design and migrations |
| `backend-api` | Backend API implementation reference |
| `build` | Autonomous engineering workflow documentation |
| `code-review` | Bug and security review |
| `creative` | Business and marketing writing |
| `data` | Data-analysis reference |
| `design-system` | Design tokens and UI components |
| `devops` | Deployment and infrastructure |
| `diagnose` | Troubleshooting and security audits |
| `docs` | READMEs, API docs, and tutorials |
| `plan` | Task decomposition reference |
| `productivity` | General productivity and templates |
| `refactor` | Code quality and maintainability |
| `research` | Web research and synthesis |
| `ship` | Git and deployment workflow guidance |
| `test-writer` | Unit-test authoring reference |
| `ui-design` | Layout, accessibility, and UI design |

A reference document may mention tools that are not available in the current core registry. The live registry and permission gate take precedence over the document.

