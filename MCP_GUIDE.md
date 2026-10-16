# MCP Setup

N.A.L.L.Y discovers and registers external MCP tools when a configured server authenticates and successfully returns its tool list. The local built-in tool baseline remains eight tools; external MCP tools are added dynamically.

## Supported integrations

| Service | Transport | Credential |
|---|---|---|
| GitHub | Streamable HTTP | OAuth |
| Notion | Streamable HTTP | OAuth |
| Gmail | Streamable HTTP | Google OAuth client and consent |
| Spotify | Streamable HTTP pilot | Spotify OAuth app / PKCE |
| Render | Streamable HTTP | `RENDER_API_KEY` |
| NallyBridge | Streamable HTTP, hosted by N.A.L.L.Y | `NALBRIDGE_MCP_TOKEN` |

The Gmail MCP server is in Google Workspace Developer Preview. Spotify's configured endpoint is a pilot and is not represented as a fully production-verified integration.

## Manage connections from Telegram

Use:

```text
/services
/connect github
/connect notion
/connect gmail
/connect spotify
/connect render
/connect nalbridge
```

For GitHub, Notion, Gmail, and Spotify, N.A.L.L.Y returns a provider authorization URL. Open that URL, complete consent, then use `/services` to check readiness. A stored token is not considered sufficient evidence that tools are loaded.

Render does not accept its API key through Telegram. Add `RENDER_API_KEY` to the backend's hosting environment, redeploy/restart, then check `/services`.

## Provider setup

### GitHub, Notion, Gmail

Set the OAuth client credentials in the hosting environment and register callbacks against the public base URL:

- `/api/oauth/github/callback`
- `/api/oauth/notion/callback`
- `/api/oauth/google/callback`

For Gmail, set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and a stable `NALLY_CRED_KEY`. The exact consent scopes must be reviewed in the provider dashboard before authorizing an account.

### Spotify

Set `SPOTIFY_CLIENT_ID` and add this redirect URI to the Spotify developer app:

```text
https://YOUR_NALLY_HOST/api/oauth/spotify/callback
```

The endpoint can be overridden with `SPOTIFY_MCP_URL`. The default points at Spotify's external pilot endpoint. The OAuth exchange has not been claimed verified against every Spotify account/app configuration.

### Render

Set `RENDER_API_KEY` on the server. N.A.L.L.Y sends it as an Authorization bearer token to `https://mcp.render.com/mcp`. Render MCP can make infrastructure changes and trigger deployments. Its calls remain subject to N.A.L.L.Y's permission gate. Never commit the key or share it in Telegram.

## NallyBridge MCP

N.A.L.L.Y hosts an authenticated Streamable HTTP MCP server at:

```text
https://YOUR_NALLY_HOST/mcp/nalbridge/mcp
```

Configure these server environment values:

- `NALBRIDGE_MCP_TOKEN`: long random bearer token required by MCP clients
- `NALLY_MCP_ALLOWED_HOSTS`: comma-separated exact hostnames accepted by MCP transport
- `NALLY_BASE_URL`: public service URL used for OAuth and Host allowlist configuration
- `NALLY_BRIDGE_TOKEN`: separate shared secret used by the connected device WebSockets

The MCP client authorization header must be `Authorization: Bearer <NALBRIDGE_MCP_TOKEN>`. The connected bridge devices still authenticate separately; enabling the MCP endpoint does not create or connect devices by itself.

NallyBridge exposes:
- `list_devices`
- `execute_device_tool` for the currently supported device capabilities `run_command`, `file_io`, and `read_file`

The server-side adapter maps public `file_io` calls to the legacy `file_ops` wire message only when communicating with existing bridge clients.

## Connection status

The authenticated backend API provides `GET /api/mcp/services`. Telegram's `/services` command uses an internally authenticated route. Status can be:

- `needs_oauth` — provider consent has not completed
- `needs_api_key` — a server-side API key is absent
- `enabled_client_connecting` — NallyBridge MCP is enabled but its local client has not yet registered tools
- `connected` — tools were discovered and registered

A service may still fail after discovery if a provider expires a token, revokes access, or changes its API.
