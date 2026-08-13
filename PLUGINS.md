# Plugins

Plugins let you extend Nally with custom tools without modifying the core codebase.

## How Plugins Work

- Plugins are Python files in the `plugins/` directory
- Loaded at startup via `registry.load_plugins()`
- **Allowlist-gated**: Only files in `ALLOWED_PLUGINS` are loaded (empty list = no plugins)
- Each plugin registers one or more `Tool` instances with the global registry

## Creating a Plugin

### 1. Create the Plugin File

Create `plugins/my_tool.py`:

```python
from nally.tools.registry import Tool, registry


class MyCustomTool(Tool):
    name = "my_custom_tool"
    description = "Does a custom thing. Use when the user wants X."
    parameters = {
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "The input to process"
            }
        },
        "required": ["input"]
    }

    def execute(self, **kwargs):
        input_value = kwargs.get("input", "")
        # Do something with input
        result = f"Processed: {input_value}"
        return result


# Register the tool
registry.register(MyCustomTool())
```

### 2. Add to Allowlist

In your `.env`:

```env
ALLOWED_PLUGINS=my_tool.py
```

Or in `nally/config.py`, modify `ALLOWED_PLUGINS`:

```python
ALLOWED_PLUGINS = ["my_tool.py"]
```

### 3. Restart

Restart Nally to load the new plugin. The tool will appear in `/api/status` tool count.

## Tool Base Class

```python
class Tool:
    name: str           # Unique tool name (snake_case)
    description: str    # What it does — shown to LLM
    parameters: dict    # JSON Schema for tool inputs
    permission: str     # "safe", "destructive", "read_only", "write"

    def execute(self, **kwargs) -> str:
        ...
```

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
from nally.tools.registry import Tool, registry


class WeatherTool(Tool):
    name = "get_weather"
    description = "Get current weather for a city. Use when the user asks about weather."
    permission = "safe"
    parameters = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name (e.g. 'Lagos', 'London')"
            }
        },
        "required": ["city"]
    }

    def execute(self, **kwargs):
        city = kwargs.get("city", "")
        url = f"https://wttr.in/{city}?format=%C+%t+%h+%w"
        try:
            resp = httpx.get(url, timeout=10)
            return resp.text.strip()
        except Exception as e:
            return f"Error: {e}"


registry.register(WeatherTool())
```

## Troubleshooting

### Plugin not loading
- Check `ALLOWED_PLUGINS` includes the filename
- Check for syntax errors in the plugin file
- Look at server logs for import errors

### Tool not appearing
- Verify `registry.register()` is called at module level
- Check tool name doesn't conflict with existing tool
- Run `python -c "from nally.tools import registry; registry.load_plugins()"` to test

### Permission denied
- Check tool's `permission` level
- Add to `permissions.json` if needed
