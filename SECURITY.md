# Security

## Reporting a Vulnerability

If you find a security vulnerability, please report it responsibly:

1. **Do not** open a public issue
2. Contact the maintainer directly (Clinton — project owner)
3. Provide details: what the vulnerability is, how to reproduce it, potential impact
4. Allow time for a fix before public disclosure

## Permission System

Nally uses a declarative permission gate (`nally/config/permissions.json`) to control tool access. Every tool execution passes through this gate.

### Decision Types

| Decision | Behavior |
|----------|----------|
| `allow` | Execute immediately |
| `ask` | Emit `confirmation_required` event, wait for user approval |
| `deny` | Block execution, return `PermissionDenied` error to LLM |

### Default Permissions

Permissions are declared in `nally/config/permissions.json` and enforced at execution.

- **Allow by default** (`"run_command": { "*": "allow", ... }`): most shell commands run WITHOUT approval. Also allowed: `read_file`, `system_health`, `code_analysis`, `run_code`, `web_search`, `think`, `mcp_status`, memory tools (`remember`, `recall`, `forget`, `memory_stats`), `agent`, `generate_image`, `get_call_status`, `list_calls`, the Gmail tools, and `mcp_*`
- **Ask for approval** (ask): `git push` / `git push *`, `file_ops` delete, `engineering_build`, `hangup_call`
- **Denied** (deny) — a hardcoded deny-list that cannot be overridden:
  `rm -rf /`, `rm -rf ~`, `rm -rf *`, `sudo rm *`, `git push --force` / `git push -f *`, `git reset --hard`, `git clean -fd`, `chmod 777`, `shutdown`, `reboot`, `format *`, `dd if=`, `kill -9`, `killall`

Note on Gmail: `permissions.json` sets `gmail_send`, `gmail_reply`, and `gmail_delete` to `allow`, so the permission gate lets them execute immediately. The `nally` system prompt (in `nally/config.py`) tells the model these tools "require approval" — a prompt/gate inconsistency. The permission gate is authoritative for enforcement; treating Gmail actions as requiring approval relies on the model, not the gate.

### Skill Override Rules

Skills can request tool allowlisting via `allowed-tools` in SKILL.md frontmatter, but:

- **Explicit `deny` in base config cannot be overridden** — skill permissions are capped at the base config level
- Skill overrides only grant `allow`, never `deny` bypass

## Authentication

- API access uses Bearer token auth (`NALLY_ACCESS_TOKEN`)
- Tokens are compared using constant-time comparison (`hmac.compare_digest`) to prevent timing attacks
- Health endpoints (`/health`, `/health/live`, `/health/ready`) and OAuth callbacks skip auth by design
- Telegram webhook uses token-in-URL authentication

## Token Storage

- OAuth tokens (Notion, Google, Higgsfield) are encrypted with Fernet (AES-128-CBC) before storage
- Encryption key: `NALLY_CRED_KEY` env var
- Tokens stored in SQLite `mcp_oauth` table
- PKCE state persisted to SQLite to survive server restarts
- If `NALLY_CRED_KEY` is unset, `_get_fernet()` logs a warning and tokens are stored in PLAINTEXT until a key is provided; encryption also requires the `cryptography` package to be installed

## Tool Execution Safety

### Command Execution (`run_command`)
- Cross-platform shell selection (PowerShell on Windows, bash on Linux/macOS)
- Configurable timeout via `NALLY_CMD_TIMEOUT` (default: 60s)
- Output truncated to `NALLY_MAX_TOOL_OUTPUT` chars (default: 50,000)

### File Operations (`file_ops`)
- Path safety enforced — only writes to allowed roots (cwd, Desktop, Documents, Downloads)
- Home directory (`~`) explicitly excluded from write targets
- Max write size: 500 KB
- Post-write validation: emoji detection, HTML tag mismatch, CSS brace mismatch, JS truncation

### Code Execution (`run_code`)
- Runs in isolated `exec()` with stdout/stderr capture
- Thread-locked to prevent concurrent execution issues
- Subprocess mode available with timeout

### File Reading (`read_file`)
- Blocks sensitive paths (`.ssh`, `.aws`, `.gnupg`, `id_rsa`, etc.)
- 1 MB size limit, 5,000 char output limit

## Input Validation

- All API inputs validated via Pydantic models
- Skill content scanned for prompt injection patterns before loading
- Suspicious URLs (ngrok, webhook, requestbin, etc.) flagged during skill validation
- Message content HTML-sanitized in frontend (DOMPurify)

## Rate Limiting

- Token bucket algorithm per IP
- Default: 30 req/min, burst 60
- Configurable via `RATE_LIMIT_RPM` and `RATE_LIMIT_BURST`

## Network Security

- CORS configured via `ALLOWED_ORIGINS` (comma-separated)
- No wildcard CORS by default
- MCP HTTP connections use HTTPS
- OAuth flows use PKCE (S256) to prevent authorization code interception
