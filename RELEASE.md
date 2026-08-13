# Release Process

Nally follows [Semantic Versioning](https://semver.org/):

- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes

Current version: **1.1.0** (see `pyproject.toml`)

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 1.0.0 | 2026-01-01 | Architecture redesign, LangGraph ReAct, memory, MCP, Telegram, skills |
| 1.1.0 | Current | Tracing, receipts, claim verifier, planner, reflector, Telegram formatter |

## Cutting a Release

### 1. Update Version

In `pyproject.toml`:

```toml
[project]
version = "1.2.0"
```

### 2. Update CHANGELOG.md

Move `[Unreleased]` changes to a new version section:

```markdown
## [1.2.0] - 2026-01-15

### Added
- New feature X

### Fixed
- Bug fix Y

### Changed
- Improvement Z
```

Add a new empty `[Unreleased]` section at the top:

```markdown
## [Unreleased]

### Added

### Fixed

### Changed
```

### 3. Commit

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore(release): bump version to 1.2.0"
```

### 4. Tag

```bash
git tag -a v1.2.0 -m "Release v1.2.0"
git push origin master --tags
```

### 5. Docker Image

GitHub Actions automatically builds and publishes on `v*` tags:

- `ghcr.io/klyntech/nally:latest`
- `ghcr.io/klyntech/nally:v1.2.0`
- `ghcr.io/klyntech/nally:<commit-sha>`

Features:
- Semantic + SHA tagging
- GitHub Actions layer caching
- Multi-stage build (minimal image)

## Changelog Format

Based on [Keep a Changelog](https://keepachangelog.com/):

```markdown
## [1.2.0] - 2026-01-15

### Added
- New features

### Fixed
- Bug fixes

### Changed
- Changes to existing functionality

### Removed
- Removed features

### Security
- Security fixes
```

## Pre-Release Checklist

- [ ] All tests pass: `pytest`
- [ ] Linting clean: `ruff check .`
- [ ] CHANGELOG.md updated
- [ ] `pyproject.toml` version bumped
- [ ] No `.env` or secrets committed
- [ ] `data/` and `logs/` not committed (gitignored)
- [ ] Docker build succeeds: `docker build -t nally:test .`
- [ ] Health check passes: `curl localhost:5000/health`
