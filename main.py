#!/usr/bin/env python3
"""
Nally - Your Personal AI Assistant
Inspired by Jarvis from Iron Man
"""
import sys
import time
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def print_banner():
    """Print Nally banner with personalized greeting"""
    from nally.config import PROVIDER, ACTIVE_PERSONALITY

    print()
    print("  +==================================================+")
    print("  |           N A L L Y  -  AI Assistant             |")
    print("  +==================================================+")
    print()
    print("  Your Personal AI Assistant (Powered by Nally)")

    # Personalized greeting
    try:
        from nally.memory.profile import user_profile
        user_name = user_profile.get_name()
        if user_name:
            print(f"  Welcome back, {user_name}!")
    except (ImportError, Exception):
        pass

    print(f"  Powered by {PROVIDER.upper()} | Personality: {ACTIVE_PERSONALITY.title()}")
    print("=" * 50)
    print()

def main():
    parser = argparse.ArgumentParser(description="Nally - Your AI Assistant")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode")
    parser.add_argument("--voice", action="store_true", help="Run in voice-only mode")
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
    
    # Load tools
    print("Loading tools...")
    from nally.tools import load_all_tools
    load_all_tools()
    
    # Start system monitor (optional)
    try:
        from nally.system import system_monitor
        print("Starting system monitor...")
        system_monitor.start_monitoring(interval=10)
    except ImportError:
        pass
    except Exception as e:
        print(f"System monitor failed: {e}")

    # Start automation engine (optional)
    automation_engine = None
    try:
        from nally.automation.engine import automation_engine
        print("Starting automation engine...")
        automation_engine.start()
    except ImportError:
        pass
    except Exception as e:
        print(f"Automation engine failed: {e}")

    # Connect to cloud database in background (non-blocking)
    def _connect_cloud():
        try:
            from nally.memory.cloud import cloud_db
            cloud_db.connect_cloud()
        except ImportError:
            pass
        except Exception as e:
            from nally.utils.logger import logger
            logger.debug(f"Cloud DB connection failed: {e}")
    import threading
    threading.Thread(target=_connect_cloud, daemon=True).start()

    if automation_engine:
        import atexit
        atexit.register(automation_engine.stop)

    print()

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

            if user_input.lower() in ['quit', 'exit', 'bye']:
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
                print(f"  [{elapsed*1000:.0f}ms]", end="")
            print()

        except KeyboardInterrupt:
            print("\n\nNally: Interrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")

def run_voice():
    """Run Nally in voice-only mode (requires nally/voice/ module)"""
    print("Voice mode requires nally/voice/ module which was not copied during migration.")
    print("Use --cli or default web mode instead.")

def run_web(port=5000):
    """Run Nally in web mode (Jarvis React UI)"""
    import webbrowser
    import threading
    import time
    import os
    
    os.environ["PORT"] = str(port)
    
    print(f"Nally Jarvis starting on http://localhost:{port}")
    print("Press Ctrl+C to stop")
    print()
    
    # Auto-open browser
    def _open():
        time.sleep(2)
        webbrowser.open(f"http://localhost:{port}")
    threading.Thread(target=_open, daemon=True).start()
    
    from nally.web.app import app
    import uvicorn
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
    import threading
    import os

    os.environ["PORT"] = str(port)

    print(f"Nally starting on http://localhost:{port} + Telegram bot")
    print("Press Ctrl+C to stop")
    print()

    # Start Telegram bot in a background thread
    def _start_telegram():
        try:
            from nally.telegram.bot import run_telegram_bot
            run_telegram_bot(polling=True)
        except Exception as e:
            print(f"Telegram bot failed: {e}")

    tg_thread = threading.Thread(target=_start_telegram, daemon=True)
    tg_thread.start()

    # Start web server (blocking)
    import webbrowser
    import time

    def _open():
        time.sleep(2)
        webbrowser.open(f"http://localhost:{port}")
    threading.Thread(target=_open, daemon=True).start()

    from nally.web.app import app
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
