# N.A.L.L.Y

N.A.L.L.Y is a Telegram-first personal agent with a small local tool core, persistent memory, bounded agent execution, and Model Context Protocol (MCP) integrations.

## Run

```bash
pip install -r requirements.txt
cp .env.example .env
# Set the model-provider credentials and Telegram credentials in .env.
python main.py
```

The default process hosts the private backend used by Telegram, OAuth callbacks, health checks, and MCP. The browser root is only a status page; browser chat and the CLI chat mode are disabled. Keep the API access token and internal bot token secret.

## Human interface

Telegram is the only chat interface. Commands:

- `/start` — instructions
- `/status` — provider, model, uptime, loaded tool count, and memory size
- `/abort` — request cancellation
- `/services` — MCP service readiness
- `/connect github`, `/connect notion`, `/connect gmail`, `/connect spotify` — start provider authorization
- `/connect render` — instructions for configuring the Render API key server-side
- `/connect nalbridge` — check/connect NallyBridge MCP

Never send API keys, OAuth client secrets, or the NallyBridge token in a Telegram message. Configure secrets in the hosting environment.

## Built-in tools

The local registry starts with these eight tools:

| Tool | Purpose |
|---|---|
| `run_command` | Run a local command under configured command rules |
| `file_io` | `list`, `make`, `delete`, `read`, and `write` |
| `web_search` | Find current web sources |
| `fetch` | Retrieve a source page |
| `remember` | Store durable facts or episodes |
| `recall` | Retrieve saved memory |
| `forget` | Remove saved memory |
| `subagent` | Delegate bounded work to a sub-agent |

External MCP tools are added only when a server connects successfully. NallyBridge tools are discovered from the local MCP endpoint after the backend starts. A service token being stored is not, by itself, proof that its tools are available.

## MCP services

N.A.L.L.Y connects to GitHub, Notion, Gmail, Spotify, and Render. It also hosts a NallyBridge MCP server for authenticated connected devices.

- GitHub, Notion, Gmail, and Spotify use provider authorization.
- Render uses `RENDER_API_KEY` as a server-side environment variable. Render MCP can perform consequential operations such as deploying services or changing configuration, so its tools must pass through N.A.L.L.Y's permission checks.
- The official Google Gmail MCP server is in Developer Preview.
- The configured Spotify MCP endpoint is a pilot; availability and authorization behavior must be verified against the Spotify account/app being used.

See [MCP_GUIDE.md](MCP_GUIDE.md) for setup and [DEPLOYMENT.md](DEPLOYMENT.md) for deployment details.

## Approval and tool safety

The permission rules live in `nally/config/permissions.json`. Reads and search can run without approval; file writes/deletes, remote-device execution, unknown MCP tools, and shell commands without an explicit allow rule require Telegram approval. If a gated action has no available approval channel, it is refused rather than silently approved.

File access is scoped to configured allowed roots. The file tool refuses to delete an entire allowed root directory. This is a guardrail, not a substitute for backups, least-privilege OS accounts, or reviewing proposed changes.

## Test and lint

```bash
pytest
ruff check .
```

## Main code

- `nally/agent/` — LangGraph agent loop, context handling, verification, and permissions
- `nally/tools/` — eight-tool local registry and common tool implementations
- `nally/mcp/` — external MCP client, OAuth, and the hosted NallyBridge MCP server
- `nally/memory/` — durable memory storage and recall
- `nally/telegram/` — sole chat interface
- `nally/web/app.py` — backend API, Telegram forwarding, OAuth callbacks, health, and MCP transport hosting
