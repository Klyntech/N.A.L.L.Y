"""File Operation Tools"""

import re
from pathlib import Path

from .registry import Tool

MAX_WRITE_SIZE = 500_000  # 500KB max write

# ── Path safety ───────────────────────────────────────────
# Only these roots are writable. Uses BASE_DIR (consistent) instead of
# Path.cwd() (which varies by how the process was launched).
def _get_allowed_roots():
    """Build allowed roots list. Called at runtime, not import time."""
    import tempfile as _tf

    from ..config import BASE_DIR

    roots = [
        BASE_DIR,  # N.A.L.L.Y project root
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
        Path(_tf.gettempdir()),  # OS temp — needed for tests + safe scratch work
    ]
    # Deduplicate resolved paths
    seen = set()
    out = []
    for r in roots:
        try:
            rp = r.resolve()
        except Exception:
            rp = r
        if rp not in seen:
            seen.add(rp)
            out.append(r)
    return out


def _is_safe_write_path(path: Path) -> bool:
    """Check if a path falls within allowed writable directories.

    Uses Path methods, not string prefix matching.
    Returns True if the resolved path is under any allowed root.
    """
    resolved = path.resolve()
    for root in _get_allowed_roots():
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _resolve_project_path(file_path: str) -> str:
    """Resolve a project name in the file path to its full path.

    If the LLM sends 'Millwright/index.html', resolve to
    'C:/Users/chuki/Desktop/Millwright/index.html'.
    """
    if not file_path:
        return file_path

    from ..agent.project_registry import registry

    parts = Path(file_path).parts
    if not parts:
        return file_path

    # Check if the first component is a known project name
    first = parts[0]
    resolved = registry.resolve(first)
    if resolved:
        # Replace first component with resolved path
        rest = Path(*parts[1:]) if len(parts) > 1 else Path("")
        return str(Path(resolved) / rest)

    return file_path


def _validate_file(path: Path, content: str) -> str:
    """Quick syntax check after file write. Returns combined warnings or empty string."""
    warnings = []
    suffix = path.suffix.lower()

    # Emoji detection — applies to ALL file types
    emoji_chars = re.findall(r"[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF\u200D\uFE0F]", content)
    if emoji_chars:
        warnings.append(
            f"EMOJI BLOCKED: Found {len(emoji_chars)} emoji in source code — use text labels or SVG icons instead"
        )

    if suffix == ".html":
        opens = len(re.findall(r"<(div|section|nav|main|header|footer|ul|li|a|form)\b", content))
        closes = len(re.findall(r"</(div|section|nav|main|header|footer|ul|li|a|form)>", content))
        if opens > 0 and closes == 0:
            warnings.append("HTML: Opening tags but no closing tags — file may be truncated")
        if abs(opens - closes) > 5:
            warnings.append(f"HTML: Tag mismatch — {opens} opens vs {closes} closes")
        # Check for meta description
        if not re.search(r'<meta\s+name=["\']description["\']', content, re.IGNORECASE):
            warnings.append("HTML: Missing <meta name='description'> — needed for SEO")
        # Check for main landmark
        if "<main" not in content.lower():
            warnings.append("HTML: Missing <main> landmark — needed for accessibility")

    elif suffix == ".css":
        opens = content.count("{")
        closes = content.count("}")
        if opens != closes:
            warnings.append(f"CSS: Brace mismatch — {opens} opens vs {closes} closes")
        # Warn on transition: all (performance anti-pattern)
        if re.search(r"transition\s*:\s*all\b", content):
            warnings.append("CSS: 'transition: all' — specify exact properties for better performance")
        # Warn on transition shorthand without property (e.g. "transition: 0.3s")
        if re.search(r"transition\s*:\s*[\d.]+s\b", content) and not re.search(r"transition\s*:\s*all\b", content):
            if not re.search(r"transition\s*:\s*[\d.]+s\s+\w", content):
                warnings.append(
                    "CSS: 'transition: 0.3s' shorthand — specify exact properties (e.g. 'transition: transform 0.3s ease')"
                )
        # Warn on 8-digit hex colors
        if re.search(r"#[0-9a-fA-F]{8}\b", content):
            warnings.append("CSS: 8-digit hex (#RRGGBBAA) — use rgba() for better browser compat")
        # Warn on overflow-x: hidden on body (breaks iOS)
        if re.search(r"overflow-x\s*:\s*hidden", content) and re.search(r"body\s*\{", content):
            warnings.append(
                "CSS: 'overflow-x: hidden' on body — breaks iOS rubber-banding, use overflow-x: clip instead"
            )
        # Warn on !important (specificity anti-pattern)
        if " !important" in content:
            warnings.append("CSS: !important — increase selector specificity instead")

    elif suffix == ".js":
        stripped = content.rstrip()
        if stripped and stripped[-1] not in (";", "}", ")", "]", "n"):
            warnings.append("JS: File may be truncated — doesn't end with ;, }, or )")
        # Warn on inline onclick with interpolation
        if re.search(r"onclick\s*=\s*['\"].*\$\{", content):
            warnings.append("JS: Inline onclick with string interpolation — use addEventListener instead")
        # Warn on native WebSocket when Socket.IO is likely needed
        if "new WebSocket(" in content and "socket.io" not in content.lower():
            warnings.append("JS: Native WebSocket — if backend uses Socket.IO, use socket.io-client instead")
        # Warn on bare var declarations
        if re.search(r"^var\s+\w+", content, re.MULTILINE):
            warnings.append("JS: Bare 'var' declarations — use 'const' or 'let' instead")
        # Warn if no IIFE or module pattern (for files > 50 lines)
        if len(content.splitlines()) > 50:
            has_iife = re.search(r"\(function\s*\(\)", content) or re.search(r"\(\(\)\s*=>", content)
            has_module = re.search(r"export\s+(default\s+)?", content) or re.search(r"import\s+", content)
            if not has_iife and not has_module:
                warnings.append("JS: No IIFE or module pattern — wrap in IIFE or use modules to avoid global pollution")

    if warnings:
        return "WARNING: " + " | ".join(warnings)
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

    def execute(self, file_path: str = "", path: str = "", **kwargs) -> str:
        file_path = file_path or path
        if not file_path:
            return "Error: no file path provided"
        try:
            path = Path(file_path)

            # Block reading sensitive paths (check path components, not substrings)
            sensitive_dirs = {".ssh", ".aws", ".gnupg"}
            sensitive_files = {"id_rsa", "id_ed25519", "passwd", "shadow"}
            path_parts = set(path.resolve().parts)
            if path_parts & sensitive_dirs:
                return f"Error: access denied for sensitive directory: {file_path}"
            if path.name in sensitive_files:
                return f"Error: access denied for sensitive file: {file_path}"

            if not path.exists():
                return f"Error: File not found: {file_path}"

            if path.stat().st_size > 1_000_000:
                return "Error: File too large (max 1MB)"

            content = path.read_text(encoding="utf-8")
            return content[:5000] + "..." if len(content) > 5000 else content
        except Exception as e:
            return f"Error reading file: {type(e).__name__}: {e}"


class FileOps(Tool):
    def __init__(self):
        super().__init__(
            name="file_ops",
            description="Write, list, mkdir, delete, move, or copy files and directories. Use read_file to read file contents.",
            permission="destructive",
            parameters={
                "action": {
                    "type": "string",
                    "enum": ["write", "list", "mkdir", "delete", "move", "copy"],
                    "description": "write = create/overwrite, list = list dir, mkdir = create folder, delete = remove, move = move/rename, copy = duplicate",
                    "required": True,
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to file or directory",
                },
                "destination": {
                    "type": "string",
                    "description": "Target path (for move/copy only)",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write (only for action=write)",
                },
                "task_id": {
                    "type": "string",
                    "description": "Optional idempotency key. If provided, the same task_id will not be re-executed within the session (safe to retry).",
                },
            },
        )

    def execute(self, action: str = "", file_path: str = "", content: str = "", path: str = "", destination: str = "", **kwargs) -> str:
        if not action:
            return 'Error: action is required. Send: {"action": "write", "file_path": "path", "content": "text"}'
        # Accept `path` as an alias for `file_path` (model sometimes sends `path`)
        file_path = file_path or path
        # Resolve project names to full paths
        file_path = _resolve_project_path(file_path)
        if destination:
            destination = _resolve_project_path(destination)
        try:
            if action == "write":
                if not file_path:
                    return "Error: file_path is required for write"
                path = Path(file_path)
                if not _is_safe_write_path(path):
                    allowed = ", ".join(str(r) for r in _get_allowed_roots())
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
                    allowed = ", ".join(str(r) for r in _get_allowed_roots())
                    return f"Error: path outside allowed directories. Write to: {allowed}"
                path.mkdir(parents=True, exist_ok=True)
                return f"Created directory: {file_path}"

            elif action == "list":
                p = Path(file_path)
                if not p.exists():
                    return f"Error: Directory not found: {file_path}"
                items = []
                for item in sorted(p.iterdir()):
                    prefix = "[dir] " if item.is_dir() else "      "
                    try:
                        size = item.stat().st_size if item.is_file() else 0
                    except (PermissionError, OSError):
                        size = 0
                    items.append(f"{prefix}{item.name} ({size // 1024}KB)")
                return "\n".join(items) if items else "Empty directory"

            elif action == "delete":
                if not file_path:
                    return "Error: file_path is required for delete"
                path = Path(file_path)
                if not _is_safe_write_path(path):
                    allowed = ", ".join(str(r) for r in _get_allowed_roots())
                    return f"Error: path outside allowed directories. Write to: {allowed}"
                if not path.exists():
                    return f"Error: path not found: {file_path}"
                if path.is_dir():
                    import shutil
                    shutil.rmtree(path)
                    return f"Deleted directory: {file_path}"
                else:
                    path.unlink()
                    return f"Deleted file: {file_path}"

            elif action == "move":
                if not file_path:
                    return "Error: file_path is required for move"
                if not destination:
                    return "Error: destination is required for move"
                src = Path(file_path)
                dst = Path(destination)
                if not _is_safe_write_path(src):
                    allowed = ", ".join(str(r) for r in _get_allowed_roots())
                    return f"Error: source path outside allowed directories. Write to: {allowed}"
                if not _is_safe_write_path(dst):
                    allowed = ", ".join(str(r) for r in _get_allowed_roots())
                    return f"Error: destination path outside allowed directories. Write to: {allowed}"
                if not src.exists():
                    return f"Error: source not found: {file_path}"
                if dst.exists():
                    return f"Error: destination already exists: {destination}"
                import shutil
                shutil.move(str(src), str(dst))
                return f"Moved {file_path} -> {destination}"

            elif action == "copy":
                if not file_path:
                    return "Error: file_path is required for copy"
                if not destination:
                    return "Error: destination is required for copy"
                src = Path(file_path)
                dst = Path(destination)
                if not _is_safe_write_path(src):
                    allowed = ", ".join(str(r) for r in _get_allowed_roots())
                    return f"Error: source path outside allowed directories. Write to: {allowed}"
                if not _is_safe_write_path(dst):
                    allowed = ", ".join(str(r) for r in _get_allowed_roots())
                    return f"Error: destination path outside allowed directories. Write to: {allowed}"
                if not src.exists():
                    return f"Error: source not found: {file_path}"
                if dst.exists():
                    return f"Error: destination already exists: {destination}"
                import shutil
                if src.is_dir():
                    shutil.copytree(str(src), str(dst))
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src), str(dst))
                return f"Copied {file_path} -> {destination}"

            else:
                return f"Error: Unknown action: {action}. Use write, list, mkdir, delete, move, or copy."
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
