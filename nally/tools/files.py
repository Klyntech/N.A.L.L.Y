"""File Operation Tools"""
import os
import re
from pathlib import Path
from .registry import Tool, registry

MAX_WRITE_SIZE = 500_000  # 500KB max write

# ── Path safety ───────────────────────────────────────────
# Only these roots are writable. Path.home() deliberately excluded
# to block ~/.ssh, ~/.aws, .gitconfig, browser profiles, etc.
_ALLOWED_ROOTS = [
    Path.cwd(),                          # project directory
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
]


def _is_safe_write_path(path: Path) -> bool:
    """Check if a path falls within allowed writable directories.

    Uses Path methods, not string prefix matching.
    Returns True if the resolved path is under any allowed root.
    """
    resolved = path.resolve()
    for root in _ALLOWED_ROOTS:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _validate_file(path: Path, content: str) -> str:
    """Quick syntax check after file write. Returns warning or empty string."""
    suffix = path.suffix.lower()

    if suffix == ".html":
        opens = len(re.findall(r'<(div|section|nav|main|header|footer|ul|li|a|form)\b', content))
        closes = len(re.findall(r'</(div|section|nav|main|header|footer|ul|li|a|form)>', content))
        if opens > 0 and closes == 0:
            return "WARNING: HTML has opening tags but no closing tags — file may be truncated"
        if abs(opens - closes) > 5:
            return f"WARNING: HTML tag mismatch — {opens} opens vs {closes} closes"

    elif suffix == ".css":
        opens = content.count("{")
        closes = content.count("}")
        if opens != closes:
            return f"WARNING: CSS brace mismatch — {opens} opens vs {closes} closes"
        # Warn on transition: all (performance anti-pattern)
        if re.search(r'transition\s*:\s*all\b', content):
            return "WARNING: CSS uses 'transition: all' — specify exact properties for better performance"
        # Warn on 8-digit hex colors
        if re.search(r'#[0-9a-fA-F]{8}\b', content):
            return "WARNING: CSS uses 8-digit hex (#RRGGBBAA) — use rgba() for better browser compat"

    elif suffix == ".js":
        stripped = content.rstrip()
        if stripped and stripped[-1] not in (";", "}", ")", "]", "n"):
            return "WARNING: JS file may be truncated — doesn't end with ;, }, or )"
        # Warn on inline onclick with interpolation
        if re.search(r"onclick\s*=\s*['\"].*\$\{", content):
            return "WARNING: JS uses inline onclick with string interpolation — use addEventListener instead"

    return ""


class ReadFile(Tool):
    def __init__(self):
        super().__init__(
            name="read_file",
            description="Read the contents of a file",
            parameters={
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read",
                    "required": True,
                }
            },
        )

    def execute(self, file_path: str) -> str:
        try:
            path = Path(file_path)
            if not path.exists():
                return f"File not found: {file_path}"

            if path.stat().st_size > 1_000_000:
                return "File too large (max 1MB)"

            content = path.read_text(encoding="utf-8")
            return content[:5000] + "..." if len(content) > 5000 else content
        except Exception as e:
            return f"Error reading file: {type(e).__name__}: {e}"


class FileOps(Tool):
    def __init__(self):
        super().__init__(
            name="file_ops",
            description="Create, write, or read files. Use action=write with file_path and content to write a file.",
            permission="destructive",
            parameters={
                "action": {
                    "type": "string",
                    "enum": ["write", "list", "mkdir"],
                    "description": "write = create/overwrite file, list = list directory, mkdir = create folder",
                    "required": True,
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to file or directory",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write (only for action=write)",
                },
            },
        )

    def execute(self, action: str = "", file_path: str = ".", content: str = "", **kwargs) -> str:
        if not action:
            return 'Error: action is required. Send: {"action": "write", "file_path": "path", "content": "text"}'
        try:
            if action == "write":
                if not file_path:
                    return "Error: file_path is required for write"
                path = Path(file_path)
                if not _is_safe_write_path(path):
                    allowed = ", ".join(str(r) for r in _ALLOWED_ROOTS)
                    return f"Error: path outside allowed directories. Write to: {allowed}"
                if content is None:
                    content = ""
                if len(content) > MAX_WRITE_SIZE:
                    return f"Error: content too large ({len(content)} chars, max {MAX_WRITE_SIZE})"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                result = f"Wrote {len(content)} chars to {file_path}"
                warning = _validate_file(path, content)
                if warning:
                    result += f"\n{warning}"
                return result

            elif action == "mkdir":
                if not file_path:
                    return "Error: file_path is required for mkdir"
                path = Path(file_path)
                if not _is_safe_write_path(path):
                    allowed = ", ".join(str(r) for r in _ALLOWED_ROOTS)
                    return f"Error: path outside allowed directories. Write to: {allowed}"
                path.mkdir(parents=True, exist_ok=True)
                return f"Created directory: {file_path}"

            elif action == "list":
                p = Path(file_path)
                if not p.exists():
                    return f"Directory not found: {file_path}"
                items = []
                for item in sorted(p.iterdir()):
                    prefix = "[dir] " if item.is_dir() else "      "
                    try:
                        size = item.stat().st_size if item.is_file() else 0
                    except (PermissionError, OSError):
                        size = 0
                    items.append(f"{prefix}{item.name} ({size // 1024}KB)")
                return "\n".join(items) if items else "Empty directory"

            else:
                return f"Unknown action: {action}. Use write, list, or mkdir."
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
