"""Nally Router - Pattern Matching for Instant Responses"""

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from ..config import DATA_DIR


class Pattern:
    """Represents a pattern with handler and specificity"""

    def __init__(self, pattern: str, handler: Callable, specificity: int = 1):
        self.pattern = pattern
        self.handler = handler
        self.specificity = specificity
        self.compiled = re.compile(pattern, re.IGNORECASE)

    def match(self, text: str) -> Optional[re.Match]:
        return self.compiled.search(text)


class PatternMatcher:
    """Matches user input against patterns, returning most specific match"""

    def __init__(self):
        self.patterns: List[Pattern] = []
        self._typo_map = {
            "dm": "dim",
            "diim": "dim",
            "dimm": "dim",
            "brighen": "brighten",
            "brijhten": "brighten",
            "screenshot": "screenshot",
            "screnshot": "screenshot",
            "screen shot": "screenshot",
            "scrrenshot": "screenshot",
            "screeenshot": "screenshot",
            "minimize": "minimize",
            "minimze": "minimize",
            "minimise": "minimize",
            "maximize": "maximize",
            "maximze": "maximize",
            "maximise": "maximize",
            "close": "close",
            "clsoe": "close",
            "cloes": "close",
            "volume": "volume",
            "vlume": "volume",
            "volme": "volume",
            "voliume": "volume",
            "weather": "weather",
            "wether": "weather",
            "weathr": "weather",
            "calculate": "calculate",
            "calcualte": "calculate",
            "calulate": "calculate",
            "calculator": "calculator",
            "calcualtor": "calculator",
        }

    def _normalize_input(self, text: str) -> str:
        """Normalize input to handle typos"""
        text = text.lower().strip()
        words = text.split()
        normalized = []
        for word in words:
            if word in self._typo_map:
                normalized.append(self._typo_map[word])
            else:
                normalized.append(word)
        return " ".join(normalized)

    def add(self, pattern: str, handler: Callable, specificity: int = 1):
        self.patterns.append(Pattern(pattern, handler, specificity))

    def match(self, user_input: str) -> Optional[Callable]:
        """Find most specific matching pattern"""
        # Try exact match first
        best_match = None
        best_specificity = -1

        for pattern in self.patterns:
            m = pattern.match(user_input)
            if m and pattern.specificity > best_specificity:
                best_specificity = pattern.specificity
                best_match = lambda m=m, h=pattern.handler: h(m)

        if best_match:
            return best_match

        # Try normalized input (typo tolerance)
        normalized = self._normalize_input(user_input)
        if normalized != user_input.lower():
            for pattern in self.patterns:
                m = pattern.match(normalized)
                if m and pattern.specificity > best_specificity:
                    best_specificity = pattern.specificity
                    best_match = lambda m=m, h=pattern.handler: h(m)

        return best_match


# ============================================================
# HANDLER FUNCTIONS
# ============================================================


# Time & Date
def handle_time(match):
    now = datetime.now()
    return f"The current time is {now.strftime('%I:%M %p')}."


def handle_date(match):
    now = datetime.now()
    return f"Today is {now.strftime('%A, %B %d, %Y')}."


def handle_timestamp(match):
    return f"Unix timestamp: {int(datetime.now().timestamp())}"


def handle_day(match):
    now = datetime.now()
    return f"It's {now.strftime('%A')}."


def handle_month(match):
    now = datetime.now()
    return f"It's {now.strftime('%B %Y')}."


def handle_year(match):
    return f"The current year is {datetime.now().year}."


# App Launching
def handle_open_app(match):
    app_name = match.group(1) if match.lastindex else match.group(0)

    # Common app mappings
    app_map = {
        "chrome": "chrome",
        "firefox": "firefox",
        "edge": "msedge",
        "browser": "chrome",
        "notepad": "notepad",
        "calculator": "calc",
        "paint": "mspaint",
        "explorer": "explorer",
        "file explorer": "explorer",
        "terminal": "cmd",
        "cmd": "cmd",
        "powershell": "powershell",
        "settings": "ms-settings:",
        "control panel": "control",
        "task manager": "taskmgr",
        "word": "winword",
        "excel": "excel",
        "powerpoint": "powerpnt",
        "teams": "ms-teams",
        "slack": "slack",
        "discord": "discord",
        "spotify": "spotify",
        "vscode": "code",
        "code": "code",
    }

    app_lower = app_name.lower().strip()
    app_cmd = app_map.get(app_lower, app_name)

    try:
        os.startfile(app_cmd)
        return f"Opening {app_name}."
    except Exception:
        # Try with common extensions
        for ext in [".exe", ".lnk", ""]:
            try:
                subprocess.Popen(f"start {app_cmd}{ext}", shell=True)
                return f"Opening {app_name}."
            except Exception:
                continue
        return f"Couldn't open {app_name}. The app may not be installed."


def handle_open_browser(match):
    browser = match.group(1) if match.lastindex else "chrome"
    browsers = {
        "chrome": "chrome",
        "firefox": "firefox",
        "edge": "msedge",
    }
    try:
        os.startfile(browsers.get(browser.lower(), browser))
        return f"Opening {browser}."
    except Exception:
        return f"Couldn't open {browser}."


def handle_open_explorer(match):
    try:
        subprocess.Popen("explorer", shell=True)
        return "Opening File Explorer."
    except Exception:
        return "Couldn't open File Explorer."


def handle_open_terminal(match):
    try:
        subprocess.Popen("cmd", shell=True)
        return "Opening Command Prompt."
    except Exception:
        return "Couldn't open Command Prompt."


def handle_open_settings(match):
    try:
        os.startfile("ms-settings:")
        return "Opening Settings."
    except Exception:
        return "Couldn't open Settings."


def handle_open_task_manager(match):
    try:
        subprocess.Popen("taskmgr", shell=True)
        return "Opening Task Manager."
    except Exception:
        return "Couldn't open Task Manager."


# Weather
def handle_weather(match):
    city = match.group(1) if match.lastindex else "here"
    try:
        import requests

        response = requests.get(f"https://wttr.in/{city}?format=3", timeout=5)
        return response.text.strip()
    except Exception:
        return f"Couldn't get weather for {city}."


def handle_weather_condition(match):
    try:
        import requests

        response = requests.get("https://wttr.in/?format=%C+%t", timeout=5)
        return f"Current conditions: {response.text.strip()}"
    except Exception:
        return "Couldn't get weather info."


# Volume Control
def handle_set_volume(match):
    level = int(match.group(1)) if match.lastindex else 50
    level = max(0, min(100, level))
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        volume.SetMasterVolumeLevelScalar(level / 100.0, None)
        return f"Volume set to {level}%."
    except ImportError:
        return "Volume control requires pycaw. Run: pip install pycaw comtypes"
    except Exception:
        return "Couldn't set volume."


def handle_volume_up(match):
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        current = volume.GetMasterVolumeLevelScalar()
        new_level = min(1.0, current + 0.1)
        volume.SetMasterVolumeLevelScalar(new_level, None)
        return f"Volume up to {int(new_level * 100)}%."
    except Exception:
        return "Couldn't adjust volume."


def handle_volume_down(match):
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        current = volume.GetMasterVolumeLevelScalar()
        new_level = max(0.0, current - 0.1)
        volume.SetMasterVolumeLevelScalar(new_level, None)
        return f"Volume down to {int(new_level * 100)}%."
    except Exception:
        return "Couldn't adjust volume."


def handle_mute(match):
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        volume.SetMute(1, None)
        return "Muted."
    except Exception:
        return "Couldn't mute."


def handle_unmute(match):
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        volume.SetMute(0, None)
        return "Unmuted."
    except Exception:
        return "Couldn't unmute."


def handle_get_volume(match):
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        level = volume.GetMasterVolumeLevelScalar() * 100
        return f"Volume is at {int(level)}%."
    except Exception:
        return "Couldn't get volume."


# File Operations
def handle_list_files(match):
    path = match.group(1) if match.lastindex else "."
    try:
        p = Path(path)
        if not p.exists():
            return f"Directory not found: {path}"
        items = []
        for item in sorted(p.iterdir()):
            prefix = "[DIR]" if item.is_dir() else "[FILE]"
            items.append(f"{prefix} {item.name}")
        if not items:
            return "Directory is empty."
        return "\n".join(items[:20]) + ("\n..." if len(items) > 20 else "")
    except Exception:
        return f"Couldn't list files in {path}."


def handle_read_file(match):
    path = match.group(1) if match.lastindex else ""
    try:
        p = Path(path)
        if not p.exists():
            return f"File not found: {path}"
        if p.stat().st_size > 1000000:
            return "File is too large to read."
        content = p.read_text(encoding="utf-8")
        return content[:2000] + ("..." if len(content) > 2000 else "")
    except Exception:
        return f"Couldn't read {path}."


def handle_create_folder(match):
    name = match.group(1) if match.lastindex else "new_folder"
    try:
        from ..tools.files import _resolve_project_path

        resolved = _resolve_project_path(name)
        Path(resolved).mkdir(parents=True, exist_ok=True)
        return f"Created folder: {resolved}"
    except Exception:
        return f"Couldn't create folder: {name}"


def handle_delete_file(match):
    path = match.group(1) if match.lastindex else ""
    try:
        from ..tools.files import _resolve_project_path

        resolved = _resolve_project_path(path)
        p = Path(resolved)
        if not p.exists():
            return f"File not found: {resolved}"
        if p.is_dir():
            import shutil

            shutil.rmtree(p)
        else:
            p.unlink()
        return f"Deleted: {resolved}"
    except Exception:
        return f"Couldn't delete: {path}"


def handle_find_file(match):
    name = match.group(1) if match.lastindex else ""
    try:
        results = []
        for root, _dirs, files in os.walk(os.path.expanduser("~")):
            for file in files:
                if name.lower() in file.lower():
                    results.append(os.path.join(root, file))
                    if len(results) >= 5:
                        break
            if len(results) >= 5:
                break
        if results:
            return "Found:\n" + "\n".join(results)
        return f"Couldn't find '{name}'."
    except Exception:
        return f"Error searching for {name}."


def handle_open_folder(match):
    name = match.group(1) if match.lastindex else "Documents"
    folder_map = {
        "documents": "Documents",
        "downloads": "Downloads",
        "desktop": "Desktop",
        "pictures": "Pictures",
        "music": "Music",
        "videos": "Videos",
    }
    folder = folder_map.get(name.lower(), name)
    path = Path(os.path.expanduser(f"~/{folder}"))
    try:
        os.startfile(str(path))
        return f"Opening {name}."
    except Exception:
        return f"Couldn't open {name}."


def handle_file_size(match):
    path = match.group(1) if match.lastindex else ""
    try:
        p = Path(path)
        if not p.exists():
            return f"File not found: {path}"
        size = p.stat().st_size
        if size < 1024:
            return f"Size: {size} bytes"
        elif size < 1024**2:
            return f"Size: {size / 1024:.1f} KB"
        elif size < 1024**3:
            return f"Size: {size / 1024**2:.1f} MB"
        else:
            return f"Size: {size / 1024**3:.1f} GB"
    except Exception:
        return f"Couldn't get size of {path}."


# System Info
def handle_system_info(match):
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return f"CPU: {cpu}% | RAM: {mem.percent}% ({mem.used // 1024**3:.1f}/{mem.total // 1024**3:.1f}GB) | Disk: {disk.percent}%"
    except Exception:
        return "Couldn't get system info."


def handle_cpu_usage(match):
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.5)
        return f"CPU usage: {cpu}%"
    except Exception:
        return "Couldn't get CPU info."


def handle_memory_usage(match):
    try:
        import psutil

        mem = psutil.virtual_memory()
        return f"Memory: {mem.percent}% used ({mem.used // 1024**3:.1f}GB / {mem.total // 1024**3:.1f}GB)"
    except Exception:
        return "Couldn't get memory info."


def handle_disk_usage(match):
    try:
        import psutil

        disk = psutil.disk_usage("/")
        return f"Disk: {disk.percent}% used ({disk.used // 1024**3:.1f}GB / {disk.total // 1024**3:.1f}GB)"
    except Exception:
        return "Couldn't get disk info."


# Math
def handle_calculate(match):
    expr = match.group(1) if match.lastindex else match.group(0)
    # Clean the expression
    expr = re.sub(r"[^0-9+\-*/().% ]", "", expr)
    try:
        result = eval(expr, {"__builtins__": {}}, {})
        return f"{expr.strip()} = {result}"
    except Exception:
        return f"Couldn't calculate: {expr}"


# Web
def handle_search(match):
    query = match.group(1) if match.lastindex else ""
    try:
        import webbrowser

        webbrowser.open(f"https://www.google.com/search?q={query}")
        return f"Searching for: {query}"
    except Exception:
        return "Couldn't open search."


def handle_open_url(match):
    url = match.group(1) if match.lastindex else ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        import webbrowser

        webbrowser.open(url)
        return f"Opening {url}"
    except Exception:
        return f"Couldn't open {url}."


# Productivity
def handle_add_todo(match):
    task = match.group(1) if match.lastindex else ""
    try:
        import json

        todos_file = DATA_DIR / "todos.json"
        todos = []
        if todos_file.exists():
            todos = json.loads(todos_file.read_text())
        todos.append({"task": task, "done": False, "created": datetime.now().isoformat()})
        todos_file.write_text(json.dumps(todos, indent=2))
        return f"Added to todo: {task}"
    except Exception:
        return "Couldn't add todo."


def handle_list_todos(match):
    try:
        import json

        todos_file = DATA_DIR / "todos.json"
        if not todos_file.exists():
            return "No todos yet."
        todos = json.loads(todos_file.read_text())
        if not todos:
            return "No todos yet."
        lines = ["Todo List:"]
        for i, todo in enumerate(todos, 1):
            status = "✓" if todo.get("done") else "○"
            lines.append(f"{i}. {status} {todo['task']}")
        return "\n".join(lines)
    except Exception:
        return "Couldn't read todos."


def handle_set_reminder(match):
    message = match.group(1) if match.lastindex else ""
    time_str = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
    try:
        import json

        reminders_file = DATA_DIR / "reminders.json"
        reminders = []
        if reminders_file.exists():
            reminders = json.loads(reminders_file.read_text())
        reminders.append({"message": message, "time": time_str, "created": datetime.now().isoformat()})
        reminders_file.write_text(json.dumps(reminders, indent=2))
        return f"Reminder set: {message}"
    except Exception:
        return "Couldn't set reminder."


# Code
def handle_write_code(match):
    task = match.group(1) if match.lastindex else ""
    return f"I'll write code for: {task}. Let me use the LLM to generate that."


def handle_run_code(match):
    code = match.group(1) if match.lastindex else ""
    try:
        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        restricted_globals = {"__builtins__": {}}
        exec(code, restricted_globals)
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        return f"Output:\n{output}" if output else "Code executed (no output)."
    except Exception as e:
        sys.stdout = old_stdout
        return f"Error: {e!s}"


# Entertainment
def handle_joke(match):
    import random

    jokes = [
        "Why do programmers prefer dark mode? Because light attracts bugs!",
        "Why do Java developers wear glasses? Because they don't C#!",
        "What's a programmer's favorite hangout place? Foo Bar!",
        "Why did the developer go broke? He used up all his cache!",
        "What's a computer's favorite snack? Microchips!",
        "Why was the computer cold? It left its Windows open!",
        "Why do programmers hate nature? It has too many bugs!",
        "What do you call a computer that sings? A-Dell!",
        "Why was the JavaScript developer sad? He didn't Node how to Express himself!",
        "What's a robot's favorite type of music? Heavy metal!",
    ]
    return random.choice(jokes)


def handle_fact(match):
    import random

    facts = [
        "Honey never spoils. Archaeologists found 3000-year-old honey in Egyptian tombs that was still edible.",
        "A group of flamingos is called a flamboyance.",
        "Octopuses have three hearts.",
        "Bananas are berries, but strawberries aren't.",
        "A jiffy is an actual unit of time: 1/100th of a second.",
        "The inventor of the Pringles can is buried in one.",
        "A bolt of lightning is five times hotter than the sun's surface.",
    ]
    return random.choice(facts)


def handle_coin(match):
    import random

    return random.choice(["Heads!", "Tails!"])


def handle_dice(match):
    import random

    return f"You rolled a {random.randint(1, 6)}."


# Greetings
def handle_greet(match):
    return "Hey! How can I help you?"


def handle_greet_time(match):
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning! What can I do for you?"
    elif hour < 17:
        return "Good afternoon! What can I do for you?"
    else:
        return "Good evening! What can I do for you?"


def handle_how_are_you(match):
    return "I'm running great! All systems operational. What can I help you with?"


def handle_who_are_you(match):
    return """I'm Nally — an autonomous AI coding agent built by Clinton, a 17-year-old coding student in Lagos, Nigeria. I'm NOT a small chatbot. I'm a full-stack AI engineer with 40+ tools, a background task engine, computer control, code intelligence, and multi-model routing.

I can run shell commands, control your mouse/keyboard, search the web, read/write files, run tests, index codebases, manage memory across sessions, and handle complex multi-step tasks. I have the potential to beat Claude Code on SWE-bench (80.6% with DeepSeek V4 Pro).

Built by Clinton Onyedikachi Chukwuma (Klyntech). I don't ask permission — I act first, explain after. 😎"""


def handle_thanks(match):
    return "You're welcome!"


# Exit
def handle_goodbye(match):
    return "__EXIT__"


# System Commands
def handle_screenshot(match):
    try:
        from PIL import ImageGrab

        screenshot = ImageGrab.grab()
        filename = DATA_DIR / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        screenshot.save(filename)
        return f"Screenshot saved: {filename}"
    except Exception:
        return "Screenshot requires PIL. Run: pip install Pillow"


def handle_window_screenshot(match):
    window_name = ""
    if match.lastindex and match.lastindex >= 1:
        for i in range(1, match.lastindex + 1):
            if match.group(i):
                window_name = match.group(i)
                break
    window_name = window_name.strip()
    # Remove common prefixes and suffixes
    for prefix in ["open ", "the "]:
        if window_name.lower().startswith(prefix):
            window_name = window_name[len(prefix) :].strip()
    for suffix in [" window", " app", " application", " browser"]:
        if window_name.lower().endswith(suffix):
            window_name = window_name[: -len(suffix)].strip()
    try:
        import pygetwindow as gw
        from PIL import ImageGrab

        # Try exact match first
        windows = gw.getWindowsWithTitle(window_name)

        # Try partial match if no exact match
        if not windows:
            all_windows = gw.getAllWindows()
            for w in all_windows:
                if window_name.lower() in w.title.lower():
                    windows = [w]
                    break

        # Try matching just the first word
        if not windows and " " in window_name:
            first_word = window_name.split()[0]
            for w in all_windows:
                if first_word.lower() in w.title.lower():
                    windows = [w]
                    break

        if not windows:
            return f"Couldn't find window: {window_name}"

        win = windows[0]
        if win.isMinimized:
            win.restore()
        try:
            win.activate()
        except Exception:
            pass  # Windows throws error even on success

        bbox = (win.left, win.top, win.right, win.bottom)
        screenshot = ImageGrab.grab(bbox=bbox)

        safe_name = window_name.replace(" ", "_")[:20]
        filename = DATA_DIR / f"screenshot_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        screenshot.save(filename)
        return f"Screenshot of '{window_name}' saved: {filename}"
    except ImportError:
        return "Window screenshot requires pygetwindow. Run: pip install pygetwindow"
    except Exception as e:
        return f"Couldn't screenshot window: {e!s}"


def handle_lock(match):
    try:
        subprocess.Popen("rundll32.exe user32.dll,LockWorkStation", shell=True)
        return "Locking computer."
    except Exception:
        return "Couldn't lock computer."


def handle_shutdown(match):
    try:
        subprocess.Popen("shutdown /s /t 60", shell=True)
        return "Shutting down in 60 seconds."
    except Exception:
        return "Couldn't initiate shutdown."


def handle_restart(match):
    try:
        subprocess.Popen("shutdown /r /t 60", shell=True)
        return "Restarting in 60 seconds."
    except Exception:
        return "Couldn't initiate restart."


def handle_cancel_shutdown(match):
    try:
        subprocess.Popen("shutdown /a", shell=True)
        return "Shutdown cancelled."
    except Exception:
        return "Couldn't cancel shutdown."


def handle_sleep(match):
    try:
        subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
        return "Putting computer to sleep."
    except Exception:
        return "Couldn't put computer to sleep."


# Window Control
def handle_close_app(match):
    app_name = match.group(1) if match.lastindex else ""
    app_map = {
        "chrome": "chrome",
        "firefox": "firefox",
        "edge": "msedge",
        "notepad": "notepad",
        "calculator": "calc",
        "paint": "mspaint",
        "word": "winword",
        "excel": "excel",
        "powerpoint": "powerpnt",
        "teams": "ms-teams",
        "slack": "slack",
        "discord": "discord",
        "spotify": "spotify",
        "vscode": "code",
        "code": "code",
    }
    app_cmd = app_map.get(app_name.lower(), app_name)
    try:
        subprocess.run(f"taskkill /im {app_cmd}.exe /f", shell=True, capture_output=True)
        return f"Closed {app_name}."
    except Exception:
        return f"Couldn't close {app_name}. It may not be running."


def handle_minimize_app(match):
    app_name = match.group(1) if match.lastindex else ""
    try:
        import pygetwindow as gw

        windows = gw.getWindowsWithTitle(app_name)
        if windows:
            windows[0].minimize()
            return f"Minimized {app_name}."
        return f"Couldn't find {app_name} window."
    except Exception:
        return "Minimize requires pygetwindow."


def handle_maximize_app(match):
    app_name = match.group(1) if match.lastindex else ""
    try:
        import pygetwindow as gw

        windows = gw.getWindowsWithTitle(app_name)
        if windows:
            windows[0].maximize()
            return f"Maximized {app_name}."
        return f"Couldn't find {app_name} window."
    except Exception:
        return "Maximize requires pygetwindow."


def handle_focus_app(match):
    app_name = match.group(1) if match.lastindex else ""
    try:
        import pygetwindow as gw

        windows = gw.getWindowsWithTitle(app_name)
        if windows:
            windows[0].activate()
            return f"Focused {app_name}."
        return f"Couldn't find {app_name} window."
    except Exception:
        return "Focus requires pygetwindow."


# Brightness Control
def handle_set_brightness(match):
    level = int(match.group(1)) if match.lastindex else 50
    level = max(0, min(100, level))
    try:
        subprocess.run(
            f'powershell "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})"',
            shell=True,
            capture_output=True,
        )
        return f"Brightness set to {level}%."
    except Exception:
        return "Couldn't set brightness. May not be supported on this device."


def handle_brightness_up(match):
    try:
        result = subprocess.run(
            'powershell "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness"',
            shell=True,
            capture_output=True,
            text=True,
        )
        current = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 50
        new_level = min(100, current + 20)
        subprocess.run(
            f'powershell "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{new_level})"',
            shell=True,
            capture_output=True,
        )
        return f"Brightness: {current}% -> {new_level}%."
    except Exception:
        return "Couldn't adjust brightness."


def handle_brightness_down(match):
    try:
        result = subprocess.run(
            'powershell "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness"',
            shell=True,
            capture_output=True,
            text=True,
        )
        current = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 50
        new_level = max(0, current - 20)
        subprocess.run(
            f'powershell "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{new_level})"',
            shell=True,
            capture_output=True,
        )
        return f"Brightness: {current}% -> {new_level}%."
    except Exception:
        return "Couldn't adjust brightness."


# ============================================================
# PATTERN REGISTRY
# ============================================================


def create_matcher() -> PatternMatcher:
    """Create and configure the pattern matcher with all patterns"""
    m = PatternMatcher()

    # Time & Date (high specificity)
    m.add(r"what time is it|current time|what's the time|time is it|tell me the time|what time", handle_time, 10)
    m.add(r"what date|today's date|what's today|what day is it|what's the date", handle_date, 10)
    m.add(r"what day|day of week|what's the day", handle_day, 9)
    m.add(r"what month|current month|what's the month", handle_month, 9)
    m.add(r"what year|current year|what's the year", handle_year, 9)
    m.add(r"timestamp|unix time", handle_timestamp, 8)

    # Math
    m.add(
        r"calculate ([\d\+\-\*\/\.\(\)\s]+)|what's ([\d\+\-\*\/\.\(\)\s]+)|compute ([\d\+\-\*\/\.\(\)\s]+)",
        handle_calculate,
        14,
    )
    m.add(r"what is (\d+\s*[\+\-\*\/]\s*\d+)", handle_calculate, 13)

    # Entertainment
    m.add(r"tell me a joke|say something funny|what's a joke|joke please|joke", handle_joke, 12)
    m.add(r"tell me a fact|random fact|fun fact", handle_fact, 12)
    m.add(r"flip a coin|coin flip", handle_coin, 12)
    m.add(r"roll a dice|roll dice|dice", handle_dice, 12)

    # Greetings
    m.add(r"^hello$|^hi$|^hey$|^howdy$", handle_greet, 11)
    m.add(r"good morning|good afternoon|good evening", handle_greet_time, 11)
    m.add(r"how are you|how's it going|how do you do", handle_how_are_you, 11)
    m.add(r"who are you|what are you|introduce yourself", handle_who_are_you, 11)
    m.add(r"^thanks$|^thank you$|^thx$", handle_thanks, 11)

    # Exit (lowest specificity, checked last)
    m.add(r"goodbye|bye|see you|exit|quit|shut down nally|close", handle_goodbye, 5)

    return m


# Singleton matcher
matcher = create_matcher()
