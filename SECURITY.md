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

The active core toolset is limited to these registered tools: `run_command`, `read_file`, `file_ops`, `fetch`, `web_search`, `remember`, `recall`, `forget`, `agent`, and `bridge_execute`.

- **Allowed directly**: `read_file`, `fetch`, `web_search`, `remember`, `recall`, `forget`, `agent`, and `bridge_execute`.
- **Shell commands**: `run_command` is allowed by its command rules except for hard-coded denials and configured restrictions. Treat shell execution as a high-impact capability.
- **File operations**: `file_ops` operations are allowed except `delete`, which requires approval.
- **Unknown tools**: tools not listed in the permission configuration default to `ask`. Having a name in a prompt does not register a tool; the runtime registry is authoritative.

The hard-coded shell deny-list cannot be overridden. It blocks dangerous patterns such as `rm -rf /`, destructive force-pushes, `git reset --hard`, `git clean -fd`, broad permission changes, shutdown/reboot, disk-formatting commands, and `kill -9`.

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
- OAuth token writes fail closed in every environment if `NALLY_CRED_KEY` is missing or invalid, or if `cryptography` is unavailable
- Legacy plaintext-token reads are permitted only for local migration; production rejects unencrypted stored tokens
- Keep `NALLY_CRED_KEY` stable and backed up securely; changing it makes existing encrypted tokens unreadable

## Tool Execution Safety

The default core set is `run_command`, `read_file`, `file_ops`, `web_search`, `fetch`, `remember`, `recall`, `forget`, `agent`, and `bridge_execute`. Explicitly connecting an MCP service can add that service's tools to the runtime registry. The runtime registry, not a hardcoded tool count in documentation, determines which tools the model receives.

### Command Execution (`run_command`)
- Cross-platform shell selection (PowerShell on Windows, bash on Linux/macOS)
- Configurable timeout via `NALLY_CMD_TIMEOUT` (default: 60s)
- Output truncated to `NALLY_MAX_TOOL_OUTPUT` chars (default: 50,000)

### File Operations (`file_ops`)
- Path safety enforced — only writes to allowed roots (cwd, Desktop, Documents, Downloads)
- Home directory (`~`) explicitly excluded from write targets
- Max write size: 500 KB
- Post-write validation: emoji detection, HTML tag mismatch, CSS brace mismatch, JS truncation

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
