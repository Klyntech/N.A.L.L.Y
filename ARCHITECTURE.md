# Architecture

## Overview

```text
Telegram user
    │
    ▼
Telegram bot
    │ authenticated internal HTTP
    ▼
FastAPI backend ────── OAuth callbacks / health / MCP transports
    │
    ▼
Session manager
    │
    ▼
LangGraph ReAct loop
    ├── Context + persistent memory
    ├── Permission gate + tool guardrails
    └── Tool registry
          ├── 8 built-in tools
          └── MCP tools from successfully connected servers
                 ├── GitHub
                 ├── Notion
                 ├── Gmail
                 ├── Spotify
                 ├── Render
                 └── NallyBridge (hosted locally)
```

The FastAPI process is the backend for Telegram and MCP. It does not expose a browser chat interface. The root route is informational; `/api/chat` returns HTTP 410. OAuth callback URLs and internal Telegram API routes remain because the backend needs them.

## Fixed local core

The initial local registry is intentionally limited to:

1. `run_command`
2. `file_io` — actions `list`, `make`, `delete`, `read`, `write`
3. `web_search`
4. `fetch`
5. `remember`
6. `recall`
7. `forget`
8. `subagent`

Connected MCP tools are dynamic and are not part of the eight-tool baseline. A persisted OAuth token alone does not prove connection health; the server needs to complete tool discovery and register schemas.

## Execution and approvals

Every tool call is checked against `nally/config/permissions.json` and the tool guardrails. Reads/searches use explicit allow rules. File writes and deletes, NallyBridge device actions, and MCP tools without an explicit safe rule require user approval. Shell commands are allow-listed by pattern; unknown commands require approval. If a tool needs approval and the execution path has no approval callback, the call is refused.

Retries, duplicate-call detection, recursion limits, and wall-clock limits are independent circuit breakers. Tool responses are evidence of tool execution, not proof of the larger task being completed; the agent must verify outcomes before claiming success.

## NallyBridge

Bridge devices retain their authenticated WebSocket connection to `/ws/bridge/{device_id}`. The server exposes MCP at:

```text
https://YOUR_NALLY_HOST/mcp/nalbridge/mcp
```

The MCP endpoint requires `Authorization: Bearer <NALBRIDGE_MCP_TOKEN>` and a configured Host allowlist. Connected devices separately authenticate their WebSocket using `NALLY_BRIDGE_TOKEN`. The backend's local MCP client connects to this endpoint after the HTTP listener is ready, then registers the discovered tools as `mcp_nalbridge_*`.

The file-I/O name exposed through MCP is `file_io`; the bridge transport internally maps it to the current bridge client's legacy wire-level `file_ops` capability.

## External MCP services

`nally/config.py` contains five external integrations: GitHub, Notion, Gmail, Spotify, and Render. HTTP API-key services read credentials from server environment variables; OAuth services store encrypted provider tokens. The client registers discovered MCP tool schemas with a stable `mcp_<service>_<tool>` prefix.

- Gmail's official MCP server is a Google Workspace Developer Preview.
- The configured Spotify endpoint is a pilot and has not been considered production-verified solely because its URL is configured.
- Render's MCP may change infrastructure; its tools therefore pass through the same permission system as other remote tools.

## Important limitations

- Memory is retrieval-based, not perfect recall.
- A successful model response is not independent verification. Consequential actions need tool receipts or an explicit follow-up check.
- NallyBridge depends on connected device availability and device-side capabilities.
- CI validates code and unit tests; it does not prove every external OAuth flow, API key, or production deployment is live.
