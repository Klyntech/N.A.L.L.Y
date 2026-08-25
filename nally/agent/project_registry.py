"""Project Registry — auto-discover project folders on disk.

Scans common directories (Desktop, Documents, Downloads) for folders that
look like projects (contain package.json, requirements.txt, pyproject.toml,
.git, app.py, main.py, README.md, etc.). Builds a name→path map that the
LLM uses to resolve project names to absolute paths.

Usage:
    from nally.agent.project_registry import registry
    registry.refresh()
    path = registry.resolve("Millwright")  # -> C:\\Users\\chuki\\Desktop\\Millwright
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("nally.projects")

# Project markers — folders containing any of these are considered projects
_PROJECT_MARKERS = {
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "composer.json",
    "pom.xml",
    "build.gradle",
    ".git",
    "app.py",
    "main.py",
    "manage.py",
    "README.md",
    "Dockerfile",
    "docker-compose.yml",
}

# Directories to skip during scanning
_SKIP_DIRS = {
    "__pycache__",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "env",
    ".env",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",
}

# Default scan directories (relative to user home)
_DEFAULT_SCAN_DIRS = [
    "Desktop",
    "Documents",
    "Downloads",
]


class ProjectRegistry:
    """Auto-discovers and caches project directories on disk."""

    def __init__(self, cache_path: Optional[Path] = None):
        self._cache_path = cache_path
        self._projects: Dict[str, str] = {}  # name -> absolute path
        self._last_scan: float = 0
        self._scan_interval: float = 300  # rescan every 5 minutes

    def _get_cache_path(self) -> Path:
        if self._cache_path:
            return self._cache_path
        from ..config import DATA_DIR
        return DATA_DIR / "projects.json"

    def resolve(self, name: str) -> Optional[str]:
        """Resolve a project name to its absolute path.

        Args:
            name: Project name (case-insensitive). Can be partial.

        Returns:
            Absolute path string if found, None otherwise.
        """
        if not name:
            return None

        # Refresh if stale
        if time.time() - self._last_scan > self._scan_interval:
            self.refresh()

        name_lower = name.lower().strip()

        # Exact match first
        for proj_name, proj_path in self._projects.items():
            if proj_name.lower() == name_lower:
                return proj_path

        # Partial match (contains)
        matches = []
        for proj_name, proj_path in self._projects.items():
            if name_lower in proj_name.lower():
                matches.append((proj_name, proj_path))

        if len(matches) == 1:
            return matches[0][1]
        elif len(matches) > 1:
            # Return closest match (shortest name = most specific)
            matches.sort(key=lambda x: len(x[0]))
            return matches[0][1]

        return None

    def get_all(self) -> Dict[str, str]:
        """Get all known projects as {name: path} dict."""
        if time.time() - self._last_scan > self._scan_interval:
            self.refresh()
        return dict(self._projects)

    def refresh(self) -> Dict[str, str]:
        """Rescan disk for projects and update the registry."""
        from ..config import BASE_DIR

        home = Path.home()
        projects = {}

        # Scan default directories
        for subdir in _DEFAULT_SCAN_DIRS:
            scan_dir = home / subdir
            if scan_dir.exists() and scan_dir.is_dir():
                self._scan_directory(scan_dir, projects, max_depth=2)

        # Also scan BASE_DIR's parent (for projects next to N.A.L.L.Y)
        parent = BASE_DIR.parent
        if parent.exists():
            self._scan_directory(parent, projects, max_depth=1, exclude={BASE_DIR.name})

        # Always include N.A.L.L.Y itself
        projects["N.A.L.L.Y"] = str(BASE_DIR)

        self._projects = projects
        self._last_scan = time.time()

        # Cache to disk
        self._save_cache(projects)

        logger.info(f"Project registry: found {len(projects)} projects")
        return dict(projects)

    def _scan_directory(
        self,
        directory: Path,
        results: Dict[str, str],
        max_depth: int = 2,
        current_depth: int = 0,
        exclude: Optional[set] = None,
    ):
        """Recursively scan a directory for project folders."""
        if current_depth > max_depth:
            return

        exclude = exclude or set()

        try:
            for entry in os.scandir(directory):
                if not entry.is_dir(follow_symlinks=False):
                    continue

                name = entry.name

                # Skip hidden dirs and known non-project dirs
                if name.startswith(".") or name in _SKIP_DIRS or name in exclude:
                    continue

                path = Path(entry.path)

                # Check if this directory is a project
                if self._is_project(path):
                    results[name] = str(path)
                    # Don't recurse deeper into project dirs
                    continue

                # Recurse into non-project directories
                if current_depth < max_depth:
                    self._scan_directory(path, results, max_depth, current_depth + 1)

        except (PermissionError, OSError) as e:
            logger.debug(f"Cannot scan {directory}: {e}")

    def _is_project(self, path: Path) -> bool:
        """Check if a directory looks like a project."""
        try:
            entries = set()
            for entry in os.scandir(path):
                if entry.is_file():
                    entries.add(entry.name)
                elif entry.is_dir() and entry.name == ".git":
                    entries.add(".git")

            # Must have at least 1 project marker
            return bool(entries & _PROJECT_MARKERS)
        except (PermissionError, OSError):
            return False

    def _save_cache(self, projects: Dict[str, str]):
        """Save project registry to disk."""
        try:
            cache_path = self._get_cache_path()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(projects, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug(f"Failed to save project cache: {e}")

    def _load_cache(self) -> Optional[Dict[str, str]]:
        """Load project registry from cache."""
        try:
            cache_path = self._get_cache_path()
            if cache_path.exists():
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if data:
                    self._projects = data
                    self._last_scan = time.time()
                    return data
        except Exception:
            pass
        return None

    def format_for_system_prompt(self) -> str:
        """Format project list for injection into system prompt."""
        projects = self.get_all()
        if not projects:
            return ""

        lines = ["KNOWN PROJECTS ON THIS MACHINE:"]
        for name, path in sorted(projects.items()):
            lines.append(f"- {name}: {path}")
        lines.append("")
        lines.append("When writing files for a project, use its FULL path from the list above.")
        lines.append("Never write project files to the N.A.L.L.Y folder unless the project IS N.A.L.L.Y.")
        lines.append("If the user mentions a project name, resolve it to the full path before writing.")

        return "\n".join(lines)


# Singleton
registry = ProjectRegistry()
