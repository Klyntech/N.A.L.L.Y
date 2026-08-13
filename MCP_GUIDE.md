# MCP Integration Guide

Model Context Protocol (MCP) connects Nally to external services like GitHub, Notion, Gmail, and more. This guide covers setup, configuration, and troubleshooting.

## What is MCP?

MCP is a standard protocol for AI assistants to interact with external tools and services. Nally supports three transport types:

| Transport | How It Works | Use Case |
|-----------|-------------|----------|
| `stdio` | Spawn a local subprocess | CLI tools, local servers |
| `http` | Connect to remote HTTP server | Cloud services, OAuth APIs |
| `http` + `oauth` | HTTP with browser OAuth flow | User-authorized services |

## Configured Services

### OAuth Services (Browser Redirect)

These require the user to authorize via browser:

| Service | Name | What It Does |
|---------|------|-------------|
| Notion | `notion` | Pages, databases, content |
| Google Gmail | `gmail` | Read, search, compose emails |
| Google Drive | `gdrive` | Files, folders, search |
| Google Calendar | `gcalendar` | Events, scheduling |
| Higgsfield | `higgsfield` | AI video generation (Kling, Sora, Veo, Seedance) |

### Token-Based Services (Manual Token)

These require pasting an API token:

| Service | Name | Token Source |
|---------|------|-------------|
| GitHub | `github` | NALLY_ACCESS_TOKEN (auto) |
| Telegram | `telegram` | `TELEGRAM_BOT_TOKEN` env var |

### stdio Services (Local Process)

| Service | Name | Command |
|---------|------|---------|
| Fetch | `fetch` | `python -m mcp_server_fetch` |

## Connecting a Service

### OAuth Flow

1. Nally detects the service has no stored token
2. Visit `http://localhost:5000` → MCP panel → Click "Connect"
3. Browser redirects to the service's OAuth page
4. Authorize Nally
5. Redirect back to `/api/oauth/{service}/callback`
6. Token is encrypted and stored in SQLite

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

## OAuth Internals

### Providers

- **Notion**: RFC 9470/8414 discovery → Dynamic Client Registration (DCR) → PKCE (S256) → token exchange
- **Google**: Manual client credentials → PKCE → shared token across Gmail/Drive/Calendar
- **Higgsfield**: DCR → PKCE → token exchange

### Token Storage

- Encrypted with Fernet (AES-128-CBC) using `NALLY_CRED_KEY`
- Stored in SQLite `mcp_oauth` table
- PKCE state persisted to survive server restarts
- Plaintext fallback if no encryption key is set

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
