"""File Operation Tools"""
import os
from pathlib import Path
from .registry import Tool, registry

MAX_WRITE_SIZE = 500_000  # 500KB max write


def _is_within_project(path: Path) -> bool:
    """Check if path is within the project directory."""
    try:
        project_root = Path(__file__).parent.parent.parent.resolve()
        path.resolve().relative_to(project_root)
        return True
    except ValueError:
        return False


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
            description="Write, list, or create directories",
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

    def execute(self, action: str, file_path: str = ".", content: str = "", **kwargs) -> str:
        try:
            if action == "write":
                if not file_path:
                    return "Error: file_path is required for write"
                if content is None:
                    content = ""
                if len(content) > MAX_WRITE_SIZE:
                    return f"Error: content too large ({len(content)} chars, max {MAX_WRITE_SIZE})"
                path = Path(file_path)
                if not _is_within_project(path):
                    return f"Error: cannot write outside project directory: {file_path}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                return f"Wrote {len(content)} chars to {file_path}"

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

            elif action == "mkdir":
                if not file_path:
                    return "Error: file_path is required for mkdir"
                path = Path(file_path)
                if not _is_within_project(path):
                    return f"Error: cannot create directory outside project: {file_path}"
                path.mkdir(parents=True, exist_ok=True)
                return f"Created directory: {file_path}"

            else:
                return f"Unknown action: {action}. Use write, list, or mkdir."
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
