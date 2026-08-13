"""Startup display — production-grade phased output with timing.

Shared between web, CLI, and telegram-only modes.
Fail loud, succeed quiet: collapsed on success, expanded on failure.
"""

import time
from datetime import datetime

from rich.console import Console
from rich.panel import Panel


class StartupDisplay:
    """Manages startup output: timed phases, MCP tree, final summary."""

    def __init__(self, console: Console = None):
        self.console = console or Console()
        self._start = time.time()
        self._phases: list[tuple[float, str, str]] = []

    def _elapsed(self) -> float:
        return time.time() - self._start

    def _ts(self) -> str:
        now = datetime.now()
        return f"{now.strftime('%H:%M:%S')}.{now.microsecond // 1000:03d}"

    def phase(self, name: str, detail: str, ok: bool = True):
        """Log a startup phase with timestamp and aligned formatting."""
        ts = self._ts()
        dots = "." * max(1, 30 - len(name))
        if ok:
            self.console.print(f"  [dim]\\[{ts}][/] {name} {dots} [green]{detail}[/]")
        else:
            self.console.print(f"  [dim]\\[{ts}][/] {name} {dots} [yellow]{detail}[/]")
        self._phases.append((self._elapsed(), name, detail))

    def mcp_summary(self, servers: list[dict], verbose: bool = False):
        """Render MCP server status — collapsed on success, expanded on failure.

        Rules:
        - Connected servers: collapsed (count shown)
        - Failed/timed out: expanded with details
        - Awaiting auth: collapsed (count shown, expected)
        - Tree only renders if there are failures OR verbose=True
        """
        connected = [s for s in servers if s["status"] == "ok"]
        failed = [s for s in servers if s["status"] in ("timeout", "error")]
        awaiting = [s for s in servers if s["status"] == "awaiting"]

        total = len(servers)
        ok_count = len(connected)
        total_tools = sum(s.get("tools", 0) for s in connected)

        # Build summary detail
        if total == 0:
            detail = "no servers configured"
        elif not failed:
            tool_word = "tool" if total_tools == 1 else "tools"
            detail = f"[green]{ok_count}/{total} connected[/] ({total_tools} {tool_word})"
        else:
            detail = f"[yellow]{ok_count}/{total} connected[/]"

        self.phase("MCP Servers", detail, ok=not failed)

        # Expand tree if failures exist or verbose
        if failed or verbose:
            self.console.print()
            self._render_mcp_tree(servers)
            self.console.print()

    def _render_mcp_tree(self, servers: list[dict]):
        """Render full MCP server tree with status icons."""
        for i, srv in enumerate(servers):
            is_last = i == len(servers) - 1
            prefix = "`--" if is_last else "|--"
            connector = "" if is_last else "|  "
            name = srv["name"]
            status = srv["status"]
            tools = srv.get("tools", 0)
            msg = srv.get("message", "")

            if status == "ok":
                tool_word = "tool" if tools == 1 else "tools"
                dots = "." * max(1, 28 - len(name))
                self.console.print(f"  {connector}{prefix} {name} {dots} [green]{tools} {tool_word}[/]")
            elif status == "awaiting":
                self.console.print(f"  {connector}{prefix} [dim](o) {name} -- {msg}[/]")
            elif status == "timeout":
                self.console.print(f"  {connector}{prefix} [red](x) {name} -- {msg}[/]")
            else:
                self.console.print(f"  {connector}{prefix} [red](x) {name} -- {msg}[/]")

    def summary(self, port: int = None, provider: str = None, model: str = None):
        """Print final startup summary panel."""
        total = self._elapsed()
        self.console.print()

        # Build status line
        parts = []
        if port:
            parts.append(f"http://localhost:{port}")
        if provider and model:
            parts.append(f"{provider.upper()}/{model}")
        status_text = "  -  ".join(parts) if parts else ""

        # Timing line
        if total < 1:
            time_str = f"{total * 1000:.0f}ms"
        else:
            time_str = f"{total:.1f}s"

        self.console.print(
            Panel(
                f"  [bold]NALLY online[/]  {status_text}\n"
                f"  [dim]Startup in {time_str}[/]",
                border_style="#7C6AEF",
                padding=(0, 1),
            )
        )
        self.console.print()


def print_banner(version: str = "1.0.0", console: Console = None):
    """Print Nally banner using pyfiglet block font + rich styling."""
    con = console or Console()

    try:
        from pyfiglet import Figlet

        f = Figlet(font="block")
        art = f.renderText("NALLY")
        from rich.text import Text

        styled = Text(art, style="#7C6AEF")
        con.print(styled)
    except Exception:
        con.print("  [bold #7C6AEF]N A L L Y[/]")

    con.print(f"          Personal AI Assistant  -  v{version}", style="dim")
    con.print()
