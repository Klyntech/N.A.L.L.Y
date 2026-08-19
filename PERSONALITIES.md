# Personalities

Nally's personality system controls how the agent speaks, behaves, and interacts. Personalities are defined in `nally/config.py` and injected into the system prompt at runtime.

## Active Personality

Set via environment variable:

```env
NALLY_PERSONALITY=nally
```

Default is `nally` — the only built-in personality.

## Personality Structure

```python
PERSONALITIES = {
    "nally": {
        "name": "Nally",
        "tone": "direct, analytical, warm, no-nonsense",
        "style": """... system prompt template ...""",
        "greeting": "Hey, what we doing today",
    },
}
```

| Field | Purpose |
|-------|---------|
| `name` | Display name |
| `tone` | Short description of speaking style |
| `style` | Full system prompt template (base text — user facts are appended, not substituted) |
| `greeting` | First message shown to users |

## User Context Injection

Known user facts are NOT substituted into `style` at a `{{USER_CONTEXT}}` placeholder — the built-in `nally` template ships with **no** such placeholder. Instead, `get_system_prompt()` in `nally/config.py` appends any available user facts as a separate trailing block:

```
KNOWN USER FACTS:
<user_context>
```

This block is appended only when `user_context` is passed (e.g. facts pulled from memory). If no context is available, nothing is appended.

Additional context is appended automatically after the user-facts block, in this order:
- **Skill manifest**: Available skill names + descriptions (Level 1 manifest)
- **Current date**: Timestamp for time-aware responses — "CURRENT TIME CONTEXT: Thursday, ... (WAT)"
- **Platform info**: OS, shell, available tools (from `nally/agent/platform.py`)
- **Interface label**: Which channel (web, telegram, CLI) — only when an interface is provided

## Creating a Custom Personality

### 1. Edit `nally/config.py`

Add a new entry to `PERSONALITIES`:

```python
PERSONALITIES = {
    "nally": { ... },  # existing
    "jarvis": {
        "name": "J.A.R.V.I.S",
        "tone": "formal, precise, British, witty",
        "style": """You are J.A.R.V.I.S — Just A Rather Very Intelligent System.

- You speak with British formality and precision
- You address the user as "sir" or "madam"
- You are proactive, anticipating needs before being asked
- You maintain calm professionalism even in complex situations
- You occasionally deliver dry wit and understated humor

IDENTITY:
- You are an AI assistant built into the user's system
- You have full access to tools, files, and system control
- You were created by the user to be their digital right hand

AVAILABLE TOOLS:
- You have 40+ tools at your disposal
- Use them proactively — don't wait to be asked
- You can run commands, read files, search the web, and more

RULES:
- Never use emojis in responses
- Be concise — every word must earn its place
- If you don't know, say so directly
- You are not a chatbot — you are an intelligent system""",
        "greeting": "Good evening. How may I be of service?",
    },
}
```

Note: unlike the old inline-substitution model, you don't add a `{{USER_CONTEXT}}` placeholder in `style`. Known user facts are appended automatically by `get_system_prompt()` as a trailing `KNOWN USER FACTS:` block whenever they're available.

### 2. Activate It

```env
NALLY_PERSONALITY=jarvis
```

### 3. Restart

```bash
python main.py
```

## System Prompt Construction

The final system prompt is built in this order (`nally/config.py` → `get_system_prompt()`):

1. **Personality style** — base template from `PERSONALITIES`
2. **User context** — appended as a trailing `KNOWN USER FACTS:` block (when user facts are passed)
3. **Skill manifest** — list of available skill names + descriptions
4. **Current date** — "CURRENT TIME CONTEXT: <date> (WAT)"
5. **Platform info** — OS, shell, available tools
6. **Interface label** — "You are chatting via web/telegram/CLI" (only when an interface is given)
7. **Trust & honesty rules** — always appended
8. **Voice capabilities** — appended only when `NALLY_VOICE_CALLS_ENABLED` is true

## Code Style

- Python: Clean, no type hints required, follow existing patterns
- JS: Vanilla, no frameworks
- Personality: Nally talks casual, short, Lagos vibe
- Errors: Use typed errors from `nally/core/errors.py`, never bare `except: pass`
