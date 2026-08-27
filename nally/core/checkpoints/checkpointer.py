"""Checkpointer — append-only turn event log with file-state snapshots.

Simplified port of vibe/core/checkpoints/checkpointer.py.

Unlike vibe's per-hunk dependency graph, this version stores
per-turn file snapshots (before/after dicts) — sufficient for
Nally's /rewind (restore whole turn) and cheaper to reason about.
Keeps the same public surface so future per-hunk upgrade is drop-in.

Log never touches disk; caller persists via FileStore.apply().
Thread-safe via internal lock (mirrors vibe's pure log).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import FileState


@dataclass(frozen=True)
class TurnRecord:
    """One completed turn's file changes."""

    turn_id: int
    started_at: float
    ended_at: float
    # {path: FileState before turn}
    before: Dict[str, FileState] = field(default_factory=dict)
    # {path: FileState after turn}
    after: Dict[str, FileState] = field(default_factory=dict)

    @property
    def changed_paths(self) -> List[str]:
        return [p for p in self.before if self.before[p].data != self.after.get(p, self.before[p]).data]

    def is_empty(self) -> bool:
        return not any(self.before[p].data != self.after.get(p, self.before[p]).data for p in self.before)


class Checkpointer:
    """Append-only log of TurnRecords.

    Usage:
        cp = Checkpointer()
        cp.begin_turn(turn_id=5)
        cp.record_pre(path, state)   # before mutation
        # ... tools run ...
        cp.record_post(path, state)  # after mutation
        cp.seal_turn()

        # Rewind:
        plan = cp.restore_plan(target_turn_id)  # dict[path -> FileState]
        file_store.apply(plan)

    Pure memory — no disk. Caller supplies FileStore for snapshot capture.
    """

    def __init__(self, max_turns: int = 100):
        self._lock = threading.RLock()
        self._turns: List[TurnRecord] = []
        self._open: Optional[dict] = None  # {turn_id, started_at, before: {}, after: {}}
        self._seq = 0
        self.max_turns = max_turns

    # ── Turn lifecycle ──────────────────────────────────────

    def has_open_turn(self) -> bool:
        with self._lock:
            return self._open is not None

    def begin_turn(self, turn_id: int) -> None:
        """Open a new turn. Raises if a turn is already open."""
        with self._lock:
            if self._open is not None:
                raise RuntimeError(f"begin_turn({turn_id}) while turn {self._open['turn_id']} still open")
            self._seq += 1
            self._open = {
                "turn_id": turn_id,
                "started_at": time.time(),
                "before": {},
                "after": {},
            }

    def record_pre(self, path: str, state: FileState) -> None:
        """Record file state before mutation (first wins per turn)."""
        with self._lock:
            if self._open is None:
                return
            if path not in self._open["before"]:
                self._open["before"][path] = state

    def record_post(self, path: str, state: FileState) -> None:
        """Record file state after mutation (last wins per turn)."""
        with self._lock:
            if self._open is None:
                return
            self._open["after"][path] = state

    def seal_turn(self) -> Optional[TurnRecord]:
        """Close the open turn and append to log. Returns the sealed record."""
        with self._lock:
            if self._open is None:
                return None
            rec = TurnRecord(
                turn_id=self._open["turn_id"],
                started_at=self._open["started_at"],
                ended_at=time.time(),
                before=dict(self._open["before"]),
                after=dict(self._open["after"]),
            )
            self._open = None
            # Keep only max_turns
            self._turns.append(rec)
            if len(self._turns) > self.max_turns:
                self._turns = self._turns[-self.max_turns:]
            return rec

    def abort_turn(self) -> None:
        """Drop the open turn without recording."""
        with self._lock:
            self._open = None

    # ── Queries ─────────────────────────────────────────────

    def list_turns(self) -> List[TurnRecord]:
        with self._lock:
            return list(self._turns)

    def get_turn(self, turn_id: int) -> Optional[TurnRecord]:
        with self._lock:
            for t in self._turns:
                if t.turn_id == turn_id:
                    return t
            return None

    def latest_turn_id(self) -> Optional[int]:
        with self._lock:
            return self._turns[-1].turn_id if self._turns else None

    # ── Rewind planning ─────────────────────────────────────

    def restore_plan(self, target_turn_id: int) -> Dict[str, FileState]:
        """Build a restore plan that rewinds to *after* target_turn_id.

        Example: turns [1,2,3,4], target=2 → revert files changed in 3,4.
        For each path changed after target, desired = state at target.
        For paths created after target, desired = absent.
        """
        with self._lock:
            if not self._turns:
                return {}
            # Find target index
            target_idx = None
            for i, t in enumerate(self._turns):
                if t.turn_id == target_turn_id:
                    target_idx = i
                    break
            if target_idx is None:
                # Target not found — if target is before first, revert all; else no-op
                if target_turn_id < self._turns[0].turn_id:
                    # Rewind before first: every path goes to its 'before' in first turn
                    plan: Dict[str, FileState] = {}
                    for t in self._turns:
                        for path, before_state in t.before.items():
                            if path not in plan:
                                # Use the earliest before as desired
                                plan[path] = before_state
                    return plan
                return {}

            # States at target: after of target
            at_target: Dict[str, FileState] = {}
            # Build by replaying up to target
            for t in self._turns[: target_idx + 1]:
                for path, after_state in t.after.items():
                    at_target[path] = after_state
                # Also keep 'before' for paths never after'd (deleted)
                for path, before_state in t.before.items():
                    if path not in at_target:
                        at_target[path] = before_state

            # Current state: after of latest
            current: Dict[str, FileState] = {}
            for t in self._turns:
                for path, after_state in t.after.items():
                    current[path] = after_state
                for path, before_state in t.before.items():
                    if path not in current:
                        current[path] = before_state
            # Also include final after for deleted files
            for t in reversed(self._turns):
                for path in t.before:
                    if path not in current:
                        current[path] = t.before[path]

            plan = {}
            all_paths = set(at_target.keys()) | set(current.keys())
            # For accurate at_target for paths not in after, use before/after logic from turns
            # Simpler: for each path that differs between current and at_target, restore to at_target or absent
            for path in all_paths:
                # Desired is what file looked like at target (after target turn)
                # If path never existed at target time, desired = absent
                desired = at_target.get(path)
                # Find actual current by checking latest after that mentions path
                cur = None
                for t in reversed(self._turns):
                    if path in t.after:
                        cur = t.after[path]
                        break
                    if path in t.before and path not in at_target:
                        cur = t.after.get(path, FileState.absent())
                        break
                if cur is None:
                    cur = current.get(path, FileState.absent())

                # If path in at_target, desired is that; else absent (created after target)
                if path not in at_target:
                    desired = FileState.absent()
                else:
                    desired = at_target[path]

                # Only include if different
                cur_data = cur.data if cur else None
                des_data = desired.data if desired else None
                if cur_data != des_data:
                    plan[path] = desired if desired else FileState.absent()

            return plan

    def drop_turns_from(self, turn_id: int) -> int:
        """Truncate log from turn_id onwards. Returns number dropped."""
        with self._lock:
            idx = None
            for i, t in enumerate(self._turns):
                if t.turn_id == turn_id:
                    idx = i
                    break
            if idx is None:
                return 0
            dropped = len(self._turns) - idx
            self._turns = self._turns[:idx]
            return dropped

    def clear(self) -> None:
        with self._lock:
            self._turns.clear()
            self._open = None

    # ── Diagnostics ─────────────────────────────────────────

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "turns": [
                    {
                        "turn_id": t.turn_id,
                        "started_at": t.started_at,
                        "ended_at": t.ended_at,
                        "before": {p: (s.data.hex()[:40] + "…" if s.data and len(s.data) > 20 else repr(s.data)) for p, s in t.before.items()},
                        "after": {p: (s.data.hex()[:40] + "…" if s.data and len(s.data) > 20 else repr(s.data)) for p, s in t.after.items()},
                    }
                    for t in self._turns
                ],
                "open": self._open["turn_id"] if self._open else None,
            }
