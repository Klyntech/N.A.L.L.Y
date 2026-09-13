# Plugins

Plugins let you extend Nally with custom tools without modifying the core codebase.

## How Plugins Work

- Plugins are Python files in the `plugins/` directory
- Loaded at startup via `registry.load_plugins()`
- **Allowlist-gated, but inverted from what you might expect**: `ALLOWED_PLUGINS` defaults to an empty list (`[]`), which **disables** the allowlist gate — every `.py` file in `plugins/` loads. Only when `ALLOWED_PLUGINS` is **non-empty** does it act as a filter: files not in the list are skipped
- Each plugin exports a module-level `register_tools(registry)` function that registers one or more `Tool` instances with the global registry. If a plugin has no `register_tools`, the loader logs it and registers nothing

## Creating a Plugin

### 1. Create the Plugin File

Create `plugins/my_tool.py`:

```python
from nally.tools.registry import Tool


class MyCustomTool(Tool):
    def __init__(self):
        super().__init__(
            name="my_custom_tool",
            description="Does a custom thing. Use when the user wants X.",
            parameters={
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "The input to process"
                    }
                },
                "required": ["input"]
            },
            permission="safe",
        )

    def execute(self, **kwargs):
        input_value = kwargs.get("input", "")
        # Do something with input
        result = f"Processed: {input_value}"
        return result


# Each plugin must export a module-level register_tools(registry) function.
# The loader calls it with the registry if present; otherwise it registers nothing.
def register_tools(registry):
    registry.register(MyCustomTool())
```

### 2. Optional: Restrict with an Allowlist

No allowlist is set by default — because `ALLOWED_PLUGINS=[]` disables the gate, **every** `.py` file in `plugins/` loads. If you only want specific plugins to load, set the allowlist in your `.env`:

```env
ALLOWED_PLUGINS=my_tool.py
```

Or in `nally/config.py`, modify `ALLOWED_PLUGINS`:

```python
ALLOWED_PLUGINS = ["my_tool.py"]
```

An empty list means "load everything" — not "load nothing".

### 3. Restart

Restart Nally to load the new plugin. The tool will appear in `/api/status` tool count.

## Tool Base Class

`Tool` is constructed with positional/keyword arguments (there is no automatic `name`/`description` class-attribute detection):

```python
class Tool:
    def __init__(self, name, description, parameters=None, permission="safe"):
        ...
    def execute(self, **kwargs) -> str:
        ...
```

| Args | Description |
|------|-------------|
| `name` | Unique tool name (snake_case) |
| `description` | What it does — shown to LLM |
| `parameters` | JSON Schema for tool inputs (default `{}`) |
| `permission` | `"safe"`, `"destructive"`, `"read_only"`, `"write"` (default `"safe"`) |

`execute()` returns a string. To return a typed success/failure, make the tool raise on error (the registry maps that to `success=False`); a result string starting with `"Error"` is also treated as a failure.

### Permission Levels

| Level | Gate Behavior |
|-------|--------------|
| `safe` | Always allowed (no approval needed) |
| `read_only` | Always allowed |
| `write` | Subject to permission gate rules |
| `destructive` | Subject to permission gate rules |

## Plugin Rules

- Files starting with `_` are skipped (use for utilities/base classes)
- Only `.py` files are loaded
- Plugins are loaded once at startup (no hot-reload)
- Import errors are caught and logged — one bad plugin won't crash the server
- Tool names must be unique — registering a duplicate overwrites (with warning)

## Example: Weather Plugin

```python
import httpx
from nally.tools.registry import Tool


def register_tools(registry):
    registry.register(Tool(
        name="get_weather",
        description="Get current weather for a city. Use when the user asks about weather.",
        permission="safe",
        parameters={
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name (e.g. 'Lagos', 'London')"
                }
            },
            "required": ["city"]
        },
    ))
```

## Troubleshooting

### Plugin not loading
- If `ALLOWED_PLUGINS` is **non-empty**, check it includes the filename (an empty list loads everything)
- Check for syntax errors in the plugin file
- Look at server logs for import errors (plugin exceptions are caught and logged)

### Tool not appearing
- Verify the plugin module exports a module-level `register_tools(registry)` function — without it, nothing is registered
- Check tool name doesn't conflict with existing tool
- Run `python -c "from nally.tools import registry; registry.load_plugins()"` to test

### Permission denied
- Check tool's `permission` level
- Add to `permissions.json` if needed
