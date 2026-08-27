"""Nally Checkpoints — file-state snapshots for rewind/undo.

Ported from mistral-vibe `core/checkpoints/` pure event log.
Simplified for Nally: per-turn snapshots stored via FileStore,
not per-hunk KEEP/REVERT (future). Provides the safety net
missing from pre-Phase 1 Nally (trust without rewind = no undo).
"""

from .checkpointer import Checkpointer
from .file_store import FileStore
from .fs import DiskFilesystem
from .models import FileState

__all__ = ["Checkpointer", "FileState", "FileStore", "DiskFilesystem"]
