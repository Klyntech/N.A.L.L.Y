#!/usr/bin/env python3
"""
Nally - Your Personal AI Assistant
Inspired by Jarvis from Iron Man
"""

import argparse
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))


def print_banner():
    """Print Nally banner using pyfiglet block font + rich styling."""
    from rich.console import Console
    from rich.text import Text

    console = Console()

    try:
        from pyfiglet import Figlet

        f = Figlet(font="block")
        art = f.renderText("NALLY")
        styled = Text(art, style="#7C6AEF")
        console.print(styled)
    except Exception:
        console.print("  [bold #7C6AEF]N A L L Y[/]")

    from nally import __version__

    console.print(f"          Personal AI Assistant  -  v{__version__}", style="dim")
    console.print()


def main():
    parser = argparse.ArgumentParser(description="Nally - Your AI Assistant")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode")
    parser.add_argument("--voice", action="store_true", help="Run in voice mode (push-to-talk)")
    parser.add_argument("--telegram", action="store_true", help="Run web server + Telegram bot")
    parser.add_argument("--telegram-only", action="store_true", help="Run Telegram bot only")
    parser.add_argument("--port", type=int, default=5000, help="Web server port (default: 5000)")
    parser.add_argument("--provider", choices=["groq", "opencode"], help="Override LLM provider")
    args = parser.parse_args()

    if args.port < 1024 or args.port > 65535:
        print(f"Error: port must be between 1024 and 65535, got {args.port}")
        sys.exit(1)

    # Override provider if specified
    if args.provider:
        import os

        os.environ["NALLY_PROVIDER"] = args.provider

    print_banner()

    # Load tools for non-web modes (web mode loads via app.py lifespan)
    if args.cli or args.telegram_only:
        from nally.tools import load_all_tools

        _tool_count, mcp_status = load_all_tools()

        # Display startup tree for non-web modes
        from rich.console import Console

        console = Console()
        console.print(f"  [bold]|--[/] Loading tools .......... [green]{_tool_count} registered[/]")
        if mcp_status:
            console.print("  [bold]|--[/] Connecting MCP servers")
            for i, srv in enumerate(mcp_status):
                is_last = i == len(mcp_status) - 1
                prefix = "|--" if not is_last else "`--"
                connector = "  " if is_last else "|  "
                name = srv["name"]
                status = srv["status"]
                tools = srv.get("tools", 0)
                msg = srv.get("message", "")
                if status == "ok":
                    tool_word = "tool" if tools == 1 else "tools"
                    dots = "." * max(1, 28 - len(name))
                    console.print(f"  {connector}{prefix} {name} {dots} [green]{tools} {tool_word}[/]")
                elif status == "awaiting":
                    console.print(f"  {connector}{prefix} [dim](o) {name} -- {msg}[/]")
                elif status == "timeout":
                    console.print(f"  {connector}{prefix} [yellow](o) {name} -- {msg}[/]")
                else:
                    console.print(f"  {connector}{prefix} [red](x) {name} -- {msg}[/]")
        console.print()

    if args.cli:
        run_cli()
    elif args.voice:
        run_voice()
    elif args.telegram_only:
        run_telegram(polling=True)
    elif args.telegram:
        run_web_with_telegram(port=args.port)
    else:
        run_web(port=args.port)


def run_cli():
    """Run Nally in CLI mode"""
    from nally.agent import get_agent

    agent = get_agent()

    print("Nally CLI Mode")
    print("-" * 40)
    print("Commands: 'quit' to exit")
    print()

    while True:
        try:
            user_input = input("You]: ").strip()

            if user_input.lower() in ["quit", "exit", "bye"]:
                print("\nNally: Goodbye!")
                break

            if not user_input:
                continue

            print("\nNally: ", end="", flush=True)

            start = time.time()
            response = agent.process(user_input)
            elapsed = time.time() - start

            print(response)

            if elapsed < 1:
                print(f"  [{elapsed * 1000:.0f}ms]", end="")
            print()

        except KeyboardInterrupt:
            print("\n\nNally: Interrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")


def run_voice():
    """Run Nally in voice mode (push-to-talk)."""
    from nally.voice.loop import run_voice_loop

    run_voice_loop()


def run_web(port=5000):
    """Run Nally in web mode (Jarvis React UI)"""
    import os
    import threading
    import time
    import webbrowser

    os.environ["PORT"] = str(port)

    # Auto-open browser
    def _open():
        time.sleep(2)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=_open, daemon=True).start()

    import uvicorn

    from nally.web.app import app

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


def run_telegram(polling=True, webhook_url=None):
    """Run Nally Telegram bot."""
    from nally.telegram.bot import run_telegram_bot

    print("Starting Nally Telegram bot...")
    print("Press Ctrl+C to stop")
    print()
    run_telegram_bot(polling=polling, webhook_url=webhook_url)


def run_web_with_telegram(port=5000):
    """Run both web server and Telegram bot concurrently."""
    import os
    import threading

    os.environ["PORT"] = str(port)

    # Start Telegram bot in a background thread
    def _start_telegram():
        try:
            from nally.telegram.bot import run_telegram_bot

            run_telegram_bot(polling=True)
        except Exception as e:
            from rich.console import Console
            Console().print(f"  [yellow]Telegram bot failed:[/] {e}")

    tg_thread = threading.Thread(target=_start_telegram, daemon=True)
    tg_thread.start()

    # Start web server (blocking)
    import time
    import webbrowser

    def _open():
        time.sleep(2)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=_open, daemon=True).start()

    import uvicorn

    from nally.web.app import app

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
