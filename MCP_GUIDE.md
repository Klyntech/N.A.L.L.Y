# MCP Integration Guide

Model Context Protocol (MCP) connects Nally to external services like GitHub, Notion, Gmail, and more. This guide covers setup, configuration, and troubleshooting.

## What is MCP?

MCP is a standard protocol for AI assistants to interact with external tools and services. Nally supports three transport types:

| Transport | How It Works | Use Case |
|-----------|-------------|----------|
| `stdio` | Spawn a local subprocess | CLI tools, local servers |
| `http` | Connect to remote HTTP server. The client tries **streamable HTTP** first, then falls back to **SSE** (`/sse`), then a raw **stateless `POST`** | Cloud services, OAuth APIs |
| `stdio` + `api_key` | Local subprocess with a token injected into its env | Token-gated local servers |
| `http` + `oauth` | HTTP with browser OAuth flow | User-authorized services |

## Configured Services

The default `MCP_SERVERS` list in `nally/config.py` registers only three servers.
The other services below exist as OAuth flows / examples but are **not** auto-loaded until
you add them to `MCP_SERVERS` manually.

### Default Servers (registered in `MCP_SERVERS`)

| Service | Name | What It Does |
|---------|------|-------------|
| GitHub | `github` | Repos, issues, PRs, code search |
| Notion | `notion` | Pages, databases, content |
| Google Gmail | `gmail` | Read, search, compose emails |

### OAuth-Only (add manually)

OAuth flows and callback endpoints exist, but are **not** registered servers by default.
Add them to `MCP_SERVERS` (`auth_mode: "oauth"`) to use them.

| Service | Name | What It Does |
|---------|------|-------------|
| Google Drive | `gdrive` | Files, folders, search |
| Google Calendar | `gcalendar` | Events, scheduling |
| Higgsfield | `higgsfield` | AI video generation (Kling, Sora, Veo, Seedance) |

### npm Packages (add manually)

These are meant to be added as `stdio` MCP servers by uncommenting/adding entries.

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

Edit `nally/config.py` → `MCP_SERVERS` list:

### HTTP Server (Remote)

```python
{
    "name": "my-service",
    "url": "https://mcp.example.com/mcp",
    "transport": "http",
    "description": "My custom service",
    "scope": "read",
    "permission": "safe",
},
```

### HTTP + OAuth Server

```python
{
    "name": "my-service",
    "url": "https://mcp.example.com/mcp",
    "transport": "http",
    "auth_mode": "oauth",
    "description": "My OAuth service",
    "scope": "read write",
    "permission": "write",
},
```

### stdio Server (Local)

```python
{
    "name": "my-tool",
    "command": "npx",
    "args": ["-y", "@example/mcp-server"],
    "transport": "stdio",
    "description": "My local tool",
    "permission": "safe",
},
```

### stdio + API Key

```python
{
    "name": "my-tool",
    "command": "npx",
    "args": ["-y", "@example/mcp-server"],
    "transport": "stdio",
    "auth_mode": "api_key",
    "env_key": "MY_API_KEY",      # Env var to read
    "env_name": "MY_API_KEY",     # Env var to inject into subprocess
    "description": "My API key tool",
    "permission": "safe",
},
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

These statuses come from the `/api/mcp/services` list built by
`connect_mcp_servers`. Note that the **`mcp_status` tool** (in the agent) uses a
different vocabulary: `Connected`, `Ready`, `Token stored (tools not loaded)`,
`Token set (not connected)`, `Disconnected`, `Unknown`.

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
- **Plaintext fallback**: if `NALLY_CRED_KEY` is unset (or the `cryptography`
  package is missing), tokens are stored in **plaintext** until a key is set

## Troubleshooting

### "Awaiting" status never changes
- Check the service URL is correct and accessible
- For OAuth: complete the browser flow
- For API key: ensure the env var is set and restart server

### Connection timeout
- Server may be slow to respond — try again
- Check network connectivity to the MCP server URL
- For stdio: verify the command exists (`which npx`, `which python`)

### Tools not appearing after connect
- Check server logs for tool registration errors
- Some MCP servers emit noisy logs during connection (suppressed by default)
- Try disconnecting and reconnecting

### OAuth token expired
- Disconnect: `POST /api/mcp/disconnect/{service}`
- Reconnect: `POST /api/mcp/connect/{service}`
- Some services support token refresh automatically
