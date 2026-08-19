"""Engineering workspace: a controlled, sandboxed output directory.

All generated artifacts and the run manifest live under a single base
directory. Path resolution refuses anything that escapes the base, and the
base defaults inside Nally's data dir (which is itself within the repo root and
therefore under the file-tool allowlist).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import EngineeringError, EngineeringStage


def slugify(text: str, max_len: int = 40) -> str:
    """Turn an arbitrary task string into a filesystem-safe slug."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "task").lower()).strip("-")
    if not cleaned:
        cleaned = "task"
    return cleaned[:max_len].strip("-")


class EngineeringWorkspace:
    """Manages artifact storage and the run manifest for one engineering run."""

    def __init__(self, base_dir: Optional[Path] = None, task: str = ""):
        from ..config import DATA_DIR

        self.base = Path(base_dir) if base_dir else (DATA_DIR / "builds")
        self.slug = slugify(task) if task else "task"
        # Uniquify to avoid clobbering a previous run with the same slug.
        self.dir = self._unique_dir(self.base, self.slug)
        self.manifest: Dict[str, Any] = {
            "task": task,
            "slug": self.slug,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "stages": [],
        }

    @staticmethod
    def _unique_dir(base: Path, slug: str) -> Path:
        base.mkdir(parents=True, exist_ok=True)
        candidate = base / slug
        if not candidate.exists():
            return candidate
        i = 2
        while True:
            candidate = base / f"{slug}-{i}"
            if not candidate.exists():
                return candidate
            i += 1

    def ensure(self) -> Path:
        """Create the workspace directory; idempotent."""
        self.dir.mkdir(parents=True, exist_ok=True)
        return self.dir

    def path_for(self, rel: str) -> Path:
        """Resolve a relative artifact path, refusing escape attempts."""
        rel = rel.strip().lstrip("/\\")
        if not rel:
            raise EngineeringError("Empty artifact path")
        target = (self.dir / rel).resolve()
        if self.dir.resolve() not in target.parents and target != self.dir.resolve():
            raise EngineeringError(f"Refusing path outside workspace: {rel}")
        return target

    def write_artifact(self, rel: str, content: str) -> Path:
        """Write an artifact file inside the workspace and return its path."""
        path = self.path_for(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def record_stage(self, stage: EngineeringStage, detail: Dict[str, Any]) -> None:
        """Append a stage entry to the in-memory manifest."""
        self.manifest.setdefault("stages", []).append(
            {
                "stage": stage.value,
                "detail": detail,
            }
        )

    def save_manifest(self) -> Path:
        """Persist the run manifest as JSON inside the workspace."""
        self.ensure()
        path = self.dir / "engineering_manifest.json"
        path.write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")
        return path

    @property
    def manifest_path(self) -> Path:
        return self.dir / "engineering_manifest.json"
