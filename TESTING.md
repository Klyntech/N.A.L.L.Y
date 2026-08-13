# Testing

Nally uses **pytest** with 19 test files covering tools, agent logic, MCP, permissions, and more.

## Run Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_graph.py

# Run tests matching a keyword
pytest -k "permission"

# Run with coverage report
pytest --cov=nally --cov-report=term-missing

# Skip slow tests
pytest -m "not slow"

# Skip integration tests (no external services)
pytest -m "not integration"
```

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures (tmp_dir, sample_text, etc.)
├── test_event_bus.py        # Event bus pub/sub
├── test_graph.py            # LangGraph agent loop, retry, doom detection
├── test_imagegen_router.py  # Image content-type routing
├── test_mcp_client.py       # MCP server connection
├── test_mcp_oauth.py        # OAuth flows (Notion, Google, Higgsfield)
├── test_permissions.py      # Permission gate (allow/ask/deny)
├── test_planner.py          # Plan-and-Execute pipeline
├── test_plugin_system.py    # Plugin loading
├── test_profile_migration.py # User profile DB migration
├── test_receipts.py         # HMAC-signed tool receipts
├── test_speech_pipeline.py  # Speech pipeline end-to-end
├── test_subagent_model.py   # Sub-agent spawning
├── test_tool_executor.py    # Tool execution + parallel runs
├── test_tool_filter.py      # Keyword-based tool selection
├── test_verifier.py         # Claim verifier (hallucination detection)
├── test_voice_formatter.py  # Text→speech formatting
└── test_websearch.py        # Web search (Parallel.ai + DuckDuckGo)
```

## Test Configuration

Configured in `pyproject.toml`:

- **Test paths**: `tests/`
- **File pattern**: `test_*.py`
- **Markers**: `slow`, `windows`, `integration`
- **Minimum coverage**: 50%

## Fixtures

Available via `conftest.py`:

| Fixture | Description |
|---------|-------------|
| `tmp_dir` | Temporary directory, cleaned up after test |
| `sample_text` | Sample string for file/write tests |
| `sample_code` | Sample Python code for execution tests |

## Writing Tests

```python
def test_something(tmp_dir):
    # tmp_dir is a Path to a clean temp directory
    result = some_function(tmp_dir / "test.txt")
    assert result.success
```

```python
@pytest.mark.slow
def test_something_slow():
    # Skipped unless explicitly run with -m slow
    pass
```

```python
@pytest.mark.integration
def test_mcp_connection():
    # Requires external MCP server — skipped by default
    pass
```
