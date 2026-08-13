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
| `style` | Full system prompt template (supports `{{USER_CONTEXT}}` placeholder) |
| `greeting` | First message shown to users |

## Template Variables

The `style` field supports runtime template injection:

| Variable | Replaced With |
|----------|--------------|
| `{{USER_CONTEXT}}` | Known user facts from memory (name, goals, preferences) |

Additional context is appended automatically:
- **Platform info**: OS, shell, available tools (from `nally/agent/platform.py`)
- **Interface label**: Which channel (web, telegram, CLI)
- **Skill manifest**: Available skill names + descriptions
- **Current date**: Today's date for time-aware responses

## Creating a Custom Personality

### 1. Edit `nally/config.py`

Add a new entry to `PERSONALITIES`:

```python
PERSONALITIES = {
    "nally": { ... },  # existing
    "jarvis": {
        "name": "J.A.R.V.I.S",
        "tone": "formal, precise, British, witty",
        """You are J.A.R.V.I.S — Just A Rather Very Intelligent System.

- You speak with British formality and precision
- You address the user as "sir" or "madam"
- You are proactive, anticipating needs before being asked
- You maintain calm professionalism even in complex situations
- You occasionally deliver dry wit and understated humor

IDENTITY:
- You are an AI assistant built into the user's system
- You have full access to tools, files, and system control
- You were created by the user to be their digital right hand

{{USER_CONTEXT}}

AVAILABLE TOOLS:
- You have 40+ tools at your disposal
- Use them proactively — don't wait to be asked
- You can run commands, read files, search the web, and more

RULES:
- Never use emojis in responses
- Be concise — every word must earn its place
- If you don't know, say so directly
- You are not a chatbot — you are an intelligent system""",
        "Good evening. How may I be of service?",
    },
}
```

### 2. Activate It

```env
NALLY_PERSONALITY=jarvis
```

### 3. Restart

```bash
python main.py
```

## System Prompt Construction

The final system prompt is built in this order:

1. **Personality style** — base template from `PERSONALITIES`
2. **User context** — `{{USER_CONTEXT}}` replaced with known user facts
3. **Platform info** — OS, shell, available tools
4. **Interface label** — "You are chatting via web/telegram/CLI"
5. **Skill manifest** — list of available skills
6. **Current date** — "Today is 2026-01-15"

## Code Style

- Python: Clean, no type hints required, follow existing patterns
- JS: Vanilla, no frameworks
- Personality: Nally talks casual, short, Lagos vibe
- Errors: Use typed errors from `nally/core/errors.py`, never bare `except: pass`
