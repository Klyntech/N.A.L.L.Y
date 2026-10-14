# MCP Integration Guide

Model Context Protocol (MCP) and OAuth integrations support account connection and service management in Nally's web UI. The simplified core agent currently uses a fixed tool registry and does not load external MCP server tools into model calls. Configuring or connecting a service here does not make its tools callable by the agent.

## What is MCP?

MCP is a standard protocol for AI assistants to interact with external tools and services. Nally supports three transport types:

| Transport | How It Works | Use Case |
|-----------|-------------|----------|
| `stdio` | Spawn a local subprocess | CLI tools, local servers |
| `http` | Connect to remote HTTP server. The client tries **streamable HTTP** first, then falls back to **SSE** (`/sse`), then a raw **stateless `POST`** | Cloud services, OAuth APIs |
| `stdio` + `api_key` | Local subprocess with a token injected into its env | Token-gated local servers |
| `http` + `oauth` | HTTP with browser OAuth flow | User-authorized services |

## Configured Services

The `MCP_SERVERS` list in `nally/config.py` describes services used by integration/account-management code. The core tool loader intentionally does not register MCP tools with the model. Editing this list alone does not expand the agent's callable tools.

### Configured Services

| Service | Name | What It Does |
|---------|------|-------------|
| GitHub | `github` | Repos, issues, PRs, code search |
| Notion | `notion` | Pages, databases, content |
| Google Gmail | `gmail` | Read, search, compose emails |

### Other OAuth integrations

OAuth flows and callback endpoints exist, but are **not** registered servers by default.
Add them to `MCP_SERVERS` (`auth_mode: "oauth"`) to use them.

| Service | Name | What It Does |
|---------|------|-------------|
| Google Drive | `gdrive` | Files, folders, search |
| Google Calendar | `gcalendar` | Events, scheduling |
| Higgsfield | `higgsfield` | AI video generation (Kling, Sora, Veo, Seedance) |

### External MCP server examples

These rows are reference examples only. Adding an entry does not expose a server's tools to the core agent.

| Service | Name | What It Does |
|---------|------|-------------|
| Telegram | `telegram` | Telegram MCP server (`telegram-bot-mcp-server`) |
| Context7 | `context7` | Library/doc context for code agents |
| Meta | `meta` | Meta's MCP server(s) |

## Connecting a Service

### OAuth Flow

1. Nally detects the service has no stored token
2. Visit `http://localhost:5000` → MCP panel → Click "Connect"
3. Browser redirects to the service's OAuth page
4. Authorize Nally
5. Redirect back to `/api/oauth/{service}/callback`
6. Token is encrypted and stored in SQLite

> **Redirect URI note**: the code uses `http://127.0.0.1:5000/api/oauth/github/callback`
> for GitHub but `http://localhost:5000/...` for the other services. When you
> register the callback in your GitHub OAuth app, use the `127.0.0.1` URI to match
> what the code sends (`.env.example` lists `localhost` — that only matters if you
> change the code or register both).

### Token Flow

1. Get a personal access token from the service
2. Submit via API: `POST /api/mcp/token/{service}` with `{"token": "..."}`
3. Or set the env var (e.g. `TELEGRAM_BOT_TOKEN`) and restart

### Disconnecting

- API: `POST /api/mcp/disconnect/{service}`
- This removes the stored OAuth token from the database
- Does NOT revoke the token at the provider (do that in your account settings)

## Adding a Custom MCP Server

Edit `nally/config.py` → `MCP_SERVERS` for service-connection metadata and account-management flows. This does not register tools with the core agent.

### HTTP Server (Remote)

```python
(
    {
        "name": "my-service",
        "url": "https://mcp.example.com/mcp",
        "transport": "http",
        "description": "My custom service",
        "scope": "read",
        "permission": "safe",
    },
)
```

### HTTP + OAuth Server

```python
(
    {
        "name": "my-service",
        "url": "https://mcp.example.com/mcp",
        "transport": "http",
        "auth_mode": "oauth",
        "description": "My OAuth service",
        "scope": "read write",
        "permission": "write",
    },
)
```

### stdio Server (Local)

```python
(
    {
        "name": "my-tool",
        "command": "npx",
        "args": ["-y", "@example/mcp-server"],
        "transport": "stdio",
        "description": "My local tool",
        "permission": "safe",
    },
)
```

### stdio + API Key

```python
(
    {
        "name": "my-tool",
        "command": "npx",
        "args": ["-y", "@example/mcp-server"],
        "transport": "stdio",
        "auth_mode": "api_key",
        "env_key": "MY_API_KEY",  # Env var to read
        "env_name": "MY_API_KEY",  # Env var to inject into subprocess
        "description": "My API key tool",
        "permission": "safe",
    },
)
```

## Connection Status

Check status via API:

```
GET /api/mcp/services
```

Status values:

| Status | Meaning |
|--------|---------|
| `ok` | Connected and working |
| `awaiting` | Waiting for user to connect (OAuth/token) |
| `timeout` | Connection timed out |
| `error` | Connection failed |

These statuses describe service connection/account-management state. They do not indicate that a connected server's tools are exposed to the model.

## OAuth Internals

### Providers

- **Notion**: RFC 9470/8414 discovery → Dynamic Client Registration (DCR) → PKCE (S256) → token exchange
- **Google**: Manual client credentials → PKCE → shared token across Gmail/Drive/Calendar
- **Higgsfield**: DCR → PKCE → token exchange
- **GitHub**: Static OAuth flow (no DCR) — reads `GITHUB_CLIENT_ID` /
  `GITHUB_CLIENT_SECRET` from env → PKCE (S256) → token exchange

### Token Storage

- Encrypted with Fernet (AES-128-CBC) using `NALLY_CRED_KEY`
- Stored in SQLite `mcp_oauth` table
- PKCE state persisted to survive server restarts
- **Production fails closed**: OAuth token storage refuses to write or read tokens without a valid `NALLY_CRED_KEY` and the `cryptography` package
- **Local development only**: legacy plaintext tokens can be read for migration; production rejects them

## Troubleshooting

### "Awaiting" status never changes
- Check the service URL is correct and accessible
- For OAuth: complete the browser flow
- For API key: ensure the env var is set and restart server

### Connection timeout
- Server may be slow to respond — try again
- Check network connectivity to the MCP server URL
- For stdio: verify the command exists (`which npx`, `which python`)

### MCP tools not appearing in chat
- This is expected with the current fixed core toolset: external MCP tool registration is disabled
- The account connection UI does not expand the model-callable tool registry

### OAuth token expired
- Disconnect: `POST /api/mcp/disconnect/{service}`
- Reconnect: `POST /api/mcp/connect/{service}`
- Some services support token refresh automatically
