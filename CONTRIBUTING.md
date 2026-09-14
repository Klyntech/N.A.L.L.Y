# Contributing to Nally

Thanks for wanting to contribute! This is a personal project, but improvements are welcome.

## Development Setup

```bash
# Clone the repo
git clone <repo-url>
cd N.A.L.L.Y

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Edit .env with your API keys
```

## Code Style

- Python: Clean, no type hints required, follow existing patterns
- JS: Vanilla, no frameworks
- Line length: 120 chars (ruff formatter)
- Quotes: Double quotes (enforced by ruff)

### Linting

```bash
# Check linting
ruff check .

# Auto-fix issues
ruff check --fix .

# Format code
ruff format .
```

## Commit Convention

Follows [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:**
- `feat` — new feature
- `fix` — bug fix
- `refactor` — code restructure (no behavior change)
- `docs` — documentation only
- `test` — adding/updating tests
- `chore` — build, CI, tooling
- `perf` — performance improvement
- `security` — security fix

**Examples:**
```
fix(graph): resolve streaming SSE loop variable scope
feat(tracing): add nested span-based execution tracer
docs(api): add API.md reference document
```

## Pull Request Process

1. Fork the repo and create a feature branch (`feat/your-feature`)
2. Make your changes — keep them focused
3. Add tests if applicable
4. Update docs if you changed public behavior, CLI flags, env vars, or deleted features
5. Run the test suite: `pytest`
6. Run linter: `ruff check .`
7. Write a clear PR description explaining what and why
8. Request review

## Documentation Policy

- **Same PR rule**: If you change code that affects user-facing behavior, update the docs in the same PR — not a follow-up.
- **Delete, don't update**: If a feature no longer exists, delete its docs. Don't leave "this feature was removed" stubs.
- **README is truth**: If the README says it works, it works. If you change setup steps, env vars, or commands, update the README.
- **CHANGELOG is history**: Past entries are frozen. Don't edit old changelog lines — add new ones.
- **Diagrams are code**: Mermaid diagrams in README/docs describe the actual architecture. Update them when structure changes.

## Project Structure

See [docs/reference/CLAUDE.md](docs/reference/CLAUDE.md) for full project structure and architecture decisions.

## Key Patterns

- **No import-time side effects**: Config loads .env but doesn't create dirs or print warnings at import
- **Thread-safe singletons**: Use double-checked locking for lazy singletons
- **Typed errors**: Use `NallyError` subclasses from `nally/core/errors.py`, never bare `except: pass`
- **Permission gate**: New tools must have a permission entry in `nally/config/permissions.json`
- **Tool receipts**: All tool executions are automatically receipted — no extra work needed

## Testing

See [docs/guides/TESTING.md](docs/guides/TESTING.md) for how to run and write tests.

## Architecture

See [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) for system design, data flow, and core patterns.
