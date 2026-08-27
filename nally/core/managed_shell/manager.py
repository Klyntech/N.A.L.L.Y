"""ManagedShellManager — persistent shell sessions with file-backed logs.

Lightweight port of vibe's TerminalSessionManager (~/.vibe/shell-tool) for Nally.
No real PTY (ConPTY/node-pty) yet — uses subprocess.Popen pipes + reader thread
which is sufficient for `npm run dev --watch`, REPLs, and long pytest without
the 60s TimeoutExpired lie. Future: swap to win32 ConPTY when needed.

Paths: <DATA_DIR>/shell-tool/sessions/<session_id>.log + .json
API:
  start(command, cwd, env, shell, background) -> TerminalSession
  read_output(session_id, cursor, max_bytes, wait_seconds) -> (info, chunk, next_cursor)
  write_stdin(session_id, text)
  list_sessions() -> list[info]
  kill(session_id) -> bool
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from nally.config import DATA_DIR
from nally.utils.logger import logger


def _get_shell_argv(shell: str | None) -> tuple[str, list[str]]:
    """Resolve shell executable + args prefix."""
    if platform.system() == "Windows":
        # honor explicit shell if given
        if shell and shell.lower() in ("pwsh", "powershell", "cmd"):
            p = shutil.which(shell)
            if p:
                if shell.lower() == "cmd":
                    return p, ["/c"]
                return p, ["-NoProfile", "-NonInteractive", "-Command"]
        for name in ("pwsh", "powershell"):
            p = shutil.which(name)
            if p:
                return p, ["-NoProfile", "-NonInteractive", "-Command"]
        return "cmd.exe", ["/c"]
    # POSIX
    for name in ("bash", "sh"):
        p = shutil.which(name)
        if p:
            return p, ["-c"]
    return "/bin/sh", ["-c"]


@dataclass
class TerminalSession:
    session_id: str
    command: str
    cwd: str
    shell: str
    output_path: str
    manifest_path: str
    created_at: float
    status: str = "running"  # running | completed | killed | timed_out
    exit_code: Optional[int] = None
    pid: Optional[int] = None


class ManagedShellManager:
    """Manages persistent shell sessions."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else (DATA_DIR / "shell-tool")
        self.sessions_dir = self.base_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, dict] = {}  # session_id -> {proc, thread, session, lock, output_path}
        self._lock = threading.RLock()
        self._load_orphaned()

    # ── Orphan recovery (sessions left running after crash) ──
    def _load_orphaned(self):
        try:
            for mf in self.sessions_dir.glob("*.json"):
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    sid = data.get("session_id")
                    if sid and data.get("status") == "running":
                        data["status"] = "orphaned"
                        mf.write_text(json.dumps(data), encoding="utf-8")
                except Exception:
                    continue
        except Exception:
            pass

    def _new_id(self, prefix: str = "shell") -> str:
        ts = time.strftime("%Y%m%d_%H%M%S")
        rnd = uuid.uuid4().hex[:6]
        return f"{prefix}_{ts}_{rnd}"

    # ── Lifecycle ──
    def start(
        self,
        command: str,
        cwd: str | None = None,
        env: dict | None = None,
        shell: str | None = None,
        background: bool = False,
    ) -> TerminalSession:
        """Start a new session running command. Returns TerminalSession."""
        session_id = self._new_id(prefix="shell")
        cwd_path = str(Path(cwd).resolve()) if cwd else str(Path.cwd().resolve())
        output_path = self.sessions_dir / f"{session_id}.log"
        manifest_path = self.sessions_dir / f"{session_id}.json"
        shell_exe, shell_args = _get_shell_argv(shell)

        # Prepare env
        run_env = os.environ.copy()
        if env:
            run_env.update({k: str(v) for k, v in env.items()})

        # On Windows, shell_args + command as single string is the PowerShell -Command style
        # For Popen we pass [shell_exe] + shell_args + [command]
        popen_cmd = [shell_exe] + shell_args + [command]

        # Ensure output log exists
        output_path.write_bytes(b"")

        # Use CREATE_NEW_PROCESS_GROUP on Windows so we can kill tree
        creationflags = 0
        if platform.system() == "Windows":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        proc = subprocess.Popen(
            popen_cmd,
            cwd=cwd_path,
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            bufsize=0,
            creationflags=creationflags,
        )

        session = TerminalSession(
            session_id=session_id,
            command=command,
            cwd=cwd_path,
            shell=shell_exe,
            output_path=str(output_path),
            manifest_path=str(manifest_path),
            created_at=time.time(),
            status="running",
            pid=proc.pid,
        )

        # Save manifest
        try:
            manifest_path.write_text(json.dumps(asdict(session)), encoding="utf-8")
        except Exception:
            pass

        # Reader thread: drain stdout -> log file
        def _reader():
            try:
                assert proc.stdout is not None
                # Read in chunks
                while True:
                    chunk = proc.stdout.read(8192)
                    if not chunk:
                        break
                    try:
                        with open(output_path, "ab") as f:
                            f.write(chunk)
                    except Exception:
                        break
            except Exception as e:
                logger.debug(f"Shell reader error {session_id}: {e}")
            finally:
                # Process exited — capture exit code
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
                with self._lock:
                    rec = self._sessions.get(session_id)
                    if rec:
                        sess: TerminalSession = rec["session"]
                        sess.status = "completed"
                        sess.exit_code = proc.returncode
                        try:
                            Path(sess.manifest_path).write_text(json.dumps(asdict(sess)), encoding="utf-8")
                        except Exception:
                            pass

        t = threading.Thread(target=_reader, daemon=True, name=f"shell-reader-{session_id}")
        t.start()

        with self._lock:
            self._sessions[session_id] = {
                "proc": proc,
                "thread": t,
                "session": session,
                "output_path": output_path,
                "manifest_path": manifest_path,
            }

        return session

    def _get_rec(self, session_id: str) -> Optional[dict]:
        with self._lock:
            rec = self._sessions.get(session_id)
            if rec:
                return rec
            # Try load from disk (orphaned)
            mf = self.sessions_dir / f"{session_id}.json"
            if mf.exists():
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    # Rehydrate minimal session
                    sess = TerminalSession(**{k: data[k] for k in TerminalSession.__dataclass_fields__ if k in data})
                    return {"session": sess, "proc": None, "thread": None, "output_path": self.sessions_dir / f"{session_id}.log", "manifest_path": mf}
                except Exception:
                    return None
            return None

    def _refresh_status(self, rec: dict) -> TerminalSession:
        sess: TerminalSession = rec["session"]
        proc: subprocess.Popen | None = rec.get("proc")
        if proc is not None:
            ret = proc.poll()
            if ret is not None and sess.status == "running":
                sess.status = "completed"
                sess.exit_code = ret
                try:
                    Path(sess.manifest_path).write_text(json.dumps(asdict(sess)), encoding="utf-8")
                except Exception:
                    pass
        return sess

    # ── IO ──
    def read_output(
        self,
        session_id: str,
        cursor: int = 0,
        max_bytes: int = 30000,
        wait_seconds: float = 0.2,
    ) -> Tuple[TerminalSession, bytes, int]:
        """Read output chunk from cursor. Returns (session, bytes, next_cursor)."""
        rec = self._get_rec(session_id)
        if rec is None:
            raise FileNotFoundError(f"Session {session_id} not found")
        sess = self._refresh_status(rec)
        path: Path = rec["output_path"] if isinstance(rec["output_path"], Path) else Path(rec["output_path"])
        # Optionally wait a bit for fresh output if at EOF and running
        if wait_seconds > 0 and sess.status == "running":
            end = time.time() + wait_seconds
            while time.time() < end:
                try:
                    size = path.stat().st_size if path.exists() else 0
                    if size > cursor:
                        break
                except Exception:
                    break
                time.sleep(0.05)
        data = b""
        next_cursor = cursor
        try:
            if path.exists():
                size = path.stat().st_size
                if cursor < size:
                    with open(path, "rb") as f:
                        f.seek(cursor)
                        data = f.read(max_bytes)
                        next_cursor = cursor + len(data)
                        # Try to avoid cutting UTF-8 mid-sequence
                        # If truncated and last bytes incomplete, backtrack
                        if len(data) == max_bytes and next_cursor < size:
                            # Check if we cut in middle of multi-byte
                            try:
                                data.decode("utf-8")
                            except UnicodeDecodeError:
                                # Trim up to 3 trailing bytes until valid
                                for trim in (1, 2, 3):
                                    try:
                                        data[:-trim].decode("utf-8")
                                        data = data[:-trim]
                                        next_cursor -= trim
                                        break
                                    except Exception:
                                        continue
                            # Also ensure we don't leave truncated at max_bytes when more exists
                else:
                    next_cursor = cursor
        except Exception as e:
            logger.debug(f"read_output error {session_id}: {e}")
        return sess, data, next_cursor

    def write_stdin(self, session_id: str, text: str) -> None:
        """Send text to session stdin. Raises if not running."""
        rec = self._get_rec(session_id)
        if rec is None:
            raise FileNotFoundError(f"Session {session_id} not found")
        sess = self._refresh_status(rec)
        if sess.status != "running":
            raise RuntimeError(f"Session {session_id} not running (status={sess.status})")
        proc: subprocess.Popen | None = rec.get("proc")
        if proc is None or proc.stdin is None:
            raise RuntimeError(f"Session {session_id} has no stdin (orphaned)")
        data = text.encode("utf-8")
        if not data.endswith(b"\n"):
            data += b"\n"
        try:
            proc.stdin.write(data)
            proc.stdin.flush()
        except BrokenPipeError as e:
            raise RuntimeError(f"Session {session_id} stdin broken: {e}")

    def kill(self, session_id: str, timeout: float = 5.0) -> bool:
        """Kill a running session. Returns True if killed."""
        rec = self._get_rec(session_id)
        if rec is None:
            return False
        proc: subprocess.Popen | None = rec.get("proc")
        sess: TerminalSession = rec["session"]
        if proc is None:
            # Orphaned — just mark killed
            sess.status = "killed"
            try:
                Path(sess.manifest_path).write_text(json.dumps(asdict(sess)), encoding="utf-8")
            except Exception:
                pass
            return True
        if proc.poll() is not None:
            sess.status = "completed"
            sess.exit_code = proc.returncode
            return False
        try:
            # Try graceful terminate first
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
            sess.status = "killed"
            sess.exit_code = proc.returncode
            try:
                Path(sess.manifest_path).write_text(json.dumps(asdict(sess)), encoding="utf-8")
            except Exception:
                pass
            return True
        except Exception as e:
            logger.warning(f"kill failed {session_id}: {e}")
            return False

    def list_sessions(self) -> List[dict]:
        """List all sessions (live + on-disk)."""
        out: List[dict] = []
        with self._lock:
            live_ids = set(self._sessions.keys())
            for sid, rec in list(self._sessions.items()):
                sess = self._refresh_status(rec)
                out.append(asdict(sess))
        # Also include on-disk orphans not in live
        try:
            for mf in self.sessions_dir.glob("*.json"):
                sid = mf.stem
                if sid in live_ids:
                    continue
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    out.append(data)
                except Exception:
                    continue
        except Exception:
            pass
        # Sort by created_at desc
        out.sort(key=lambda d: d.get("created_at", 0), reverse=True)
        return out

    def inspect(self, session_id: str, max_bytes: int = 10000) -> dict:
        """Return session info + tail."""
        rec = self._get_rec(session_id)
        if rec is None:
            raise FileNotFoundError(f"Session {session_id} not found")
        sess = self._refresh_status(rec)
        _, data, _ = self.read_output(session_id, cursor=0, max_bytes=max_bytes, wait_seconds=0)
        try:
            tail = data.decode("utf-8", errors="replace")
        except Exception:
            tail = repr(data[:1000])
        return {"session": asdict(sess), "tail": tail[-4000:] if len(tail) > 4000 else tail}


# Singleton
_manager: Optional[ManagedShellManager] = None
_lock = threading.Lock()

def get_manager() -> ManagedShellManager:
    global _manager
    if _manager is None:
        with _lock:
            if _manager is None:
                _manager = ManagedShellManager()
    return _manager
