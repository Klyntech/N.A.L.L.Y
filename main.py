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
    parser.add_argument("--port", type=int, default=5000, help="Web server port (default: 5000)")
    parser.add_argument("--provider", choices=["groq", "opencode"], help="Override LLM provider")
    args = parser.parse_args()
    
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
    except (ImportError, Exception):
        pass

    # Start automation engine (optional)
    automation_engine = None
    try:
        from nally.automation.engine import automation_engine
        print("Starting automation engine...")
        automation_engine.start()
    except (ImportError, Exception):
        pass

    # Connect to cloud database in background (non-blocking)
    def _connect_cloud():
        try:
            from nally.memory.cloud import cloud_db
            cloud_db.connect_cloud()
        except Exception:
            pass
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
    else:
        run_web(port=args.port)

def run_cli():
    """Run Nally in CLI mode"""
    from nally.agent import get_agent
    agent = get_agent()
    
    # Try to import system monitor (optional)
    system_monitor = None
    try:
        from nally.system import system_monitor
    except (ImportError, Exception):
        pass
    
    print("Nally CLI Mode")
    print("-" * 40)
    print("Commands: 'quit' to exit, 'status' for system info")
    print()
    
    while True:
        try:
            # Show status indicator
            if system_monitor:
                status = system_monitor.get_status()
                status_icon = {"normal": "OK", "warning": "BUSY", "critical": "OVERLOAD"}
                print(f"[{status_icon[status.get('status', 'normal')]}] ", end="", flush=True)
            
            user_input = input("You]: ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'bye']:
                print("\nNally: Goodbye! Have a great day!")
                break
            
            if user_input.lower() == 'status':
                if system_monitor:
                    print(f"\nNally: {system_monitor.get_usage_summary()}")
                else:
                    print("\nNally: System monitor not available.")
                continue
            
            if not user_input:
                continue
            
            # Check system status (warn but still allow)
            if system_monitor:
                can_run, msg = system_monitor.can_start_task()
                if not can_run:
                    print(f"\nNally: {msg}")
                    print("  (Proceeding anyway...)")
            
            print("\nNally: ", end="", flush=True)
            
            # Process with timing
            start = time.time()
            response = agent.process(user_input)
            elapsed = time.time() - start
            
            print(response)
            
            # Show timing for local patterns
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


if __name__ == "__main__":
    main()
