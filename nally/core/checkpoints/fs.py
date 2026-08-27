"""Filesystem abstraction — protocol + disk implementation.

Mirrors vibe/core/checkpoints/fs.py but with Path safety.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Filesystem(Protocol):
    def read_bytes(self, path: str) -> bytes | None: ...
    def write_bytes(self, path: str, data: bytes) -> None: ...
    def remove(self, path: str) -> None: ...
    def exists(self, path: str) -> bool: ...


class DiskFilesystem:
    """Real disk — reads/writes under allowed paths only.

    No allowlist check here; caller (Checkpointer/FileStore) governs.
    """

    def read_bytes(self, path: str) -> bytes | None:
        p = Path(path)
        try:
            return p.read_bytes()
        except FileNotFoundError:
            return None
        except IsADirectoryError:
            return None

    def write_bytes(self, path: str, data: bytes) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def remove(self, path: str) -> None:
        p = Path(path)
        try:
            if p.is_dir():
                import shutil
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)
        except FileNotFoundError:
            pass

    def exists(self, path: str) -> bool:
        return Path(path).exists()
