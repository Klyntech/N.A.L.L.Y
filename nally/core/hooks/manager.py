"""HookManager — loads hooks.json and runs matching hooks per event.

Mirrors vibe's core/hooks/manager.py but smaller: command-only hooks
(shell) for now, no http/mcp_tool/prompt/agent types yet.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List

from nally.config import BASE_DIR
from nally.utils.logger import logger

from .models import HookConfig, HookEvent, HookInvocation, HookResult

DEFAULT_HOOKS_PATH = BASE_DIR / "nally" / "config" / "hooks.json"


def _wildcard_match(pattern: str, value: str) -> bool:
    if pattern == "*":
        return True
    return fnmatch.fnmatch(value.lower(), pattern.lower())


class HookManager:
    """Loads hooks.json, matches and executes per event."""

    def __init__(self, hooks_path: Path | None = None):
        self.hooks_path = hooks_path or DEFAULT_HOOKS_PATH
        self._hooks: List[HookConfig] = []
        self._lock = threading.RLock()
        self._load()

    def _load(self):
        self._hooks.clear()
        path = self.hooks_path
        if not path.exists():
            # Also try nally/config/hooks.json fallback
            alt = BASE_DIR / "hooks.json"
            if alt.exists():
                path = alt
            else:
                return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Support both {"hooks": [...] } and [...] top-level
            raw = data.get("hooks", data) if isinstance(data, dict) else data
            if not isinstance(raw, list):
                raw = [raw]
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                # Expand event-specific grouping: {"PreToolUse": [{"matcher":...}]} vs flat list
                if "event" not in entry and len(entry) == 1:
                    # {"PreToolUse": [...]} style
                    for ev, hooks in entry.items():
                        if isinstance(hooks, list):
                            for h in hooks:
                                h2 = dict(h)
                                h2["event"] = ev
                                self._hooks.append(HookConfig.from_dict(h2))
                        elif isinstance(hooks, dict):
                            hooks2 = dict(hooks)
                            hooks2["event"] = ev
                            self._hooks.append(HookConfig.from_dict(hooks2))
                else:
                    self._hooks.append(HookConfig.from_dict(entry))
            logger.info(f"Loaded {len(self._hooks)} hooks from {path}")
        except Exception as e:
            logger.warning(f"Failed to load hooks from {self.hooks_path}: {e}")

    def reload(self):
        with self._lock:
            self._load()

    def _matching(self, event: HookEvent, tool_name: str, tool_args: Dict[str, Any]) -> List[HookConfig]:
        out = []
        with self._lock:
            hooks = list(self._hooks)
        for h in hooks:
            if h.event != event:
                continue
            if not _wildcard_match(h.matcher, tool_name):
                continue
            if h.tool_pattern:
                # Check tool input match
                val = tool_args.get("command") or tool_args.get("action") or " ".join(str(v) for v in tool_args.values() if isinstance(v, str))
                if not _wildcard_match(h.tool_pattern, str(val)):
                    continue
            out.append(h)
        return out

    def run_pre_tool(self, tool_name: str, tool_args: Dict[str, Any], cwd: str | None = None, session_id: str | None = None) -> HookResult:
        """Run PreToolUse hooks. If any deny, return deny (first wins)."""
        hooks = self._matching(HookEvent.PreToolUse, tool_name, tool_args)
        if not hooks:
            return HookResult.passthrough()
        inv = HookInvocation(event=HookEvent.PreToolUse, tool_name=tool_name, tool_args=tool_args, cwd=cwd, session_id=session_id)
        for h in hooks:
            res = self._exec(h, inv)
            if res.decision == "deny":
                logger.info(f"Hook {h.name} denied {tool_name}: {res.reason}")
                return res
            # allow with additionalContext is advisory for PreToolUse — ignore, only deny matters
        return HookResult.passthrough()

    def run_post_tool(
        self, tool_name: str, tool_args: Dict[str, Any], tool_output: str, tool_success: bool, cwd: str | None = None, session_id: str | None = None
    ) -> HookResult:
        """Run PostToolUse hooks. Accumulates additionalContext across all hooks."""
        hooks = self._matching(HookEvent.PostToolUse, tool_name, tool_args)
        if not hooks:
            # Also check PostToolUseFailure subset
            if not tool_success:
                hooks = self._matching(HookEvent.PostToolUseFailure, tool_name, tool_args)
                if not hooks:
                    return HookResult.passthrough()
            else:
                return HookResult.passthrough()
        if not tool_success:
            # Include failure hooks too
            hooks = hooks + self._matching(HookEvent.PostToolUseFailure, tool_name, tool_args)
            # dedup by name
            seen = set()
            uniq = []
            for h in hooks:
                if h.name not in seen:
                    seen.add(h.name)
                    uniq.append(h)
            hooks = uniq

        inv = HookInvocation(event=HookEvent.PostToolUse, tool_name=tool_name, tool_args=tool_args, tool_output=tool_output, tool_success=tool_success, cwd=cwd, session_id=session_id)
        contexts: List[str] = []
        for h in hooks:
            res = self._exec(h, inv)
            if res.additionalContext:
                contexts.append(res.additionalContext)
        if contexts:
            return HookResult(decision="allow", additionalContext="\n".join(contexts))
        return HookResult.passthrough()

    def _exec(self, hook: HookConfig, invocation: HookInvocation) -> HookResult:
        """Execute one hook command with stdin JSON, capped stdout."""
        stdin_data = json.dumps(invocation.to_json()).encode("utf-8")
        try:
            # Use shell for command (hook commands are shell snippets)
            proc = subprocess.Popen(
                hook.command,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=invocation.cwd or str(BASE_DIR),
            )
            try:
                stdout, stderr = proc.communicate(input=stdin_data, timeout=hook.timeout)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    stdout, stderr = proc.communicate(timeout=2)
                except Exception:
                    stdout, stderr = b"", b"timed out"
                return HookResult(decision="allow", timed_out=True, exit_code=124, stdout=stdout.decode(errors="replace"), stderr=stderr.decode(errors="replace"))
            exit_code = proc.returncode if proc.returncode is not None else 0
            out_str = stdout.decode("utf-8", errors="replace").strip()
            err_str = stderr.decode("utf-8", errors="replace").strip()
            # Exit 2 = explicit block (Claude convention)
            if exit_code == 2:
                return HookResult(decision="deny", reason=err_str or out_str or "Blocked by hook", exit_code=exit_code, stdout=out_str, stderr=err_str)
            if exit_code != 0 and not out_str:
                # Non-zero without JSON → non-blocking error unless stdout has decision
                logger.debug(f"Hook {hook.name} exited {exit_code}: {err_str[:200]}")
                return HookResult.passthrough(exit_code=exit_code, stdout=out_str, stderr=err_str)
            if not out_str:
                return HookResult.passthrough(exit_code=exit_code, stdout=out_str, stderr=err_str)
            try:
                data = json.loads(out_str)
                return HookResult.from_json(data, exit_code=exit_code, stdout=out_str, stderr=err_str)
            except json.JSONDecodeError:
                # Plain text stdout with no JSON → treat as additionalContext for PostToolUse
                if hook.event in (HookEvent.PostToolUse, HookEvent.PostToolUseFailure):
                    return HookResult(decision="allow", additionalContext=out_str, exit_code=exit_code, stdout=out_str, stderr=err_str)
                return HookResult.passthrough(exit_code=exit_code, stdout=out_str, stderr=err_str)
        except Exception as e:
            logger.warning(f"Hook exec failed {hook.name}: {e}")
            return HookResult.passthrough(exit_code=1, stderr=str(e))


# Singleton
_manager: HookManager | None = None
_manager_lock = threading.Lock()

def get_hook_manager() -> HookManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = HookManager()
    return _manager
