"""Tool access abstraction.

The loop only touches the filesystem / shell through a `Toolbox`. The real
implementation reuses Nally's existing, safety-hardened tools (path allowlists,
command timeouts, destructive-command gating) via the registry and permission
gate. A `FakeToolbox` provides an in-memory filesystem + scripted results so the
full loop can be exercised in tests with no real side effects.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Protocol, Tuple, runtime_checkable

from .models import EngineeringError


@runtime_checkable
class Toolbox(Protocol):
    """Filesystem + shell surface the engineering loop is allowed to use."""

    def write_file(self, path: str, content: str) -> str:
        ...

    def read_file(self, path: str) -> str:
        ...

    def list_dir(self, path: str) -> List[str]:
        ...

    def run_command(self, command: str) -> Tuple[str, bool]:
        ...

    def run_tests(self, path: str = "") -> Tuple[str, bool]:
        ...

    def run_lint(self, path: str = "") -> Tuple[str, bool]:
        ...


class RealToolbox:
    """Delegates to Nally's registered tools while honoring the permission gate.

    Destructive decisions marked ``deny`` in permissions.json are always blocked.
    Decisions marked ``ask`` are, within this explicitly opt-in autonomous
    subsystem, auto-approved (and logged) when ``auto_approve_ask`` is True.
    Path allowlists and command timeouts live inside the underlying tools, so
    they remain enforced regardless of this flag.
    """

    def __init__(self, auto_approve_ask: bool = True):
        self.auto_approve_ask = auto_approve_ask

    def _exec(self, name: str, args: Dict[str, object]) -> Tuple[str, bool]:
        try:
            from ..tools.permissions import gate as permission_gate
            from ..tools.registry import registry
        except Exception as exc:
            raise EngineeringError("Tool registry unavailable: " + str(exc)) from exc

        decision = permission_gate.check(name, args)
        if decision.value == "deny":
            raise EngineeringError(f"Tool '{name}' denied by permission gate.")
        if decision.value == "ask" and not self.auto_approve_ask:
            raise EngineeringError(
                f"Tool '{name}' requires approval but auto-approve is disabled."
            )
        return registry.execute(name, args)

    def write_file(self, path: str, content: str) -> str:
        result, _ = self._exec(
            "file_ops", {"action": "write", "file_path": path, "content": content}
        )
        return result

    def read_file(self, path: str) -> str:
        result, _ = self._exec("read_file", {"file_path": path})
        return result

    def list_dir(self, path: str) -> List[str]:
        result, _ = self._exec("file_ops", {"action": "list", "file_path": path})
        return [line for line in result.splitlines() if line.strip()]

    def run_command(self, command: str) -> Tuple[str, bool]:
        return self._exec("run_command", {"command": command})

    def run_tests(self, path: str = "") -> Tuple[str, bool]:
        return self._exec("code_analysis", {"action": "test", "path": path})

    def run_lint(self, path: str = "") -> Tuple[str, bool]:
        return self._exec("code_analysis", {"action": "lint", "path": path})


class FakeToolbox:
    """In-memory toolbox for tests. No real files or processes are touched."""

    def __init__(
        self,
        fs: Optional[Dict[str, str]] = None,
        command_results: Optional[Dict[str, Tuple[str, bool]]] = None,
        test_result: Any = ("3 passed", True),
        lint_result: Any = ("", True),
    ):
        self.fs: Dict[str, str] = dict(fs or {})
        self.command_results: Dict[str, Tuple[str, bool]] = dict(command_results or {})
        self.test_result = test_result
        self.lint_result = lint_result
        self.writes: List[Tuple[str, str]] = []

    @staticmethod
    def _next(scripted: Any) -> Tuple[str, bool]:
        if isinstance(scripted, list):
            if len(scripted) > 1:
                return scripted.pop(0)
            return scripted[0]
        return scripted

    def write_file(self, path: str, content: str) -> str:
        self.fs[path] = content
        self.writes.append((path, content))
        return f"Wrote {len(content)} chars to {path}"

    def read_file(self, path: str) -> str:
        if path in self.fs:
            return self.fs[path]
        return f"Error: File not found: {path}"

    def list_dir(self, path: str) -> List[str]:
        prefix = path.rstrip("/\\") + "/" if path else ""
        if prefix:
            return sorted(p for p in self.fs if p.startswith(prefix))
        return sorted(self.fs)

    def run_command(self, command: str) -> Tuple[str, bool]:
        for needle, outcome in self.command_results.items():
            if needle in command:
                return outcome
        return ("", True)

    def run_tests(self, path: str = "") -> Tuple[str, bool]:
        return self._next(self.test_result)

    def run_lint(self, path: str = "") -> Tuple[str, bool]:
        return self._next(self.lint_result)
