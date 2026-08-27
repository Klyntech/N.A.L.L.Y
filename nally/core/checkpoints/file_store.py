"""FileStore — snapshot helper around Filesystem.

Thin wrapper used by Checkpointer/Recorder to capture FileState.
Mirrors vibe/core/checkpoints/file_store.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from .fs import DiskFilesystem, Filesystem
from .models import FileState


class FileStore:
    """Reads file snapshots and applies restore plans."""

    def __init__(self, fs: Filesystem | None = None):
        self.fs = fs or DiskFilesystem()

    def read(self, path: str) -> FileState:
        """Capture current FileState for path."""
        data = self.fs.read_bytes(path)
        if data is None:
            return FileState.absent()
        return FileState.from_bytes(data)

    def apply(self, plan: Dict[str, FileState]) -> Dict[str, str]:
        """Apply a restore plan {path: desired_state}.

        Returns {path: error} for any failed restores (best-effort, no raise).
        """
        errors: Dict[str, str] = {}
        for path, desired in plan.items():
            try:
                cur = self.read(path)
                if cur.data == desired.data:
                    continue  # already correct
                if desired.data is None:
                    if cur.exists:
                        self.fs.remove(path)
                else:
                    self.fs.write_bytes(path, desired.data)
            except Exception as e:
                errors[path] = str(e)
        return errors
