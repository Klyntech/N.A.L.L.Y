"""Checkpoint models — FileState and helpers.

Mirrors vibe/core/checkpoints/models.py FileState but self-contained.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class FileState:
    """Snapshot of a file at a moment in time.

    data=None  → file absent (deleted / never created)
    data=bytes → file exists with that content (may be empty b'')
    """

    data: Optional[bytes]

    @property
    def exists(self) -> bool:
        return self.data is not None

    @property
    def is_binary(self) -> bool:
        return self.data is not None and b"\x00" in self.data

    @classmethod
    def absent(cls) -> "FileState":
        return cls(data=None)

    @classmethod
    def from_bytes(cls, data: bytes) -> "FileState":
        return cls(data=data)

    @classmethod
    def from_text(cls, text: str, encoding: str = "utf-8") -> "FileState":
        return cls(data=text.encode(encoding))

    def to_text(self, encoding: str = "utf-8") -> Optional[str]:
        if self.data is None:
            return None
        try:
            return self.data.decode(encoding)
        except UnicodeDecodeError:
            return None
