"""Nally Logging System"""

import io
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path

# Fix Windows console encoding for emoji/unicode (only if not already wrapped)
if sys.platform == "win32" and hasattr(sys.stdout, "buffer") and not isinstance(sys.stdout, io.TextIOWrapper):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass  # Already wrapped or not available


class NallyLogger:
    """Centralized logger for Nally"""

    def __init__(self, name: str = "nally", log_dir: Path = None):
        self.log_dir = log_dir or Path(__file__).parent.parent.parent / "logs"
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        if not self.logger.handlers:
            self._setup_handlers()

    def _setup_handlers(self):
        # Console handler (INFO and above)
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(console)

        # File handler with daily rotation (1MB max per file, keep 7 days)
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            logfile = self.log_dir / f"nally-{today}.log"
            file_handler = logging.handlers.RotatingFileHandler(
                logfile, maxBytes=1_000_000, backupCount=7, encoding="utf-8"
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
            self.logger.addHandler(file_handler)
        except Exception:
            # Log to console only if file logging fails
            self.logger.warning("Could not create log file, logging to console only")

    def debug(self, msg: str):
        self.logger.debug(msg)

    def info(self, msg: str):
        self.logger.info(msg)

    def warning(self, msg: str):
        self.logger.warning(msg)

    def error(self, msg: str, exc_info: bool = False):
        self.logger.error(msg, exc_info=exc_info)

    def tool_call(self, tool_name: str, args: dict, result: str):
        """Log a tool call"""
        args_str = str(args)[:200]
        result_str = str(result)[:200] if not isinstance(result, str) else result[:200]
        self.debug(f"TOOL: {tool_name}({args_str}) -> {result_str}")

    def llm_call(self, provider: str, model: str, duration_ms: float):
        """Log an LLM call"""
        self.debug(f"LLM: {provider}/{model} in {duration_ms:.0f}ms")

    def user_input(self, text: str):
        """Log user input"""
        self.info(f"You: {text[:200]}")

    def nally_response(self, text: str):
        """Log Nally's response"""
        self.info(f"Nally: {text[:200]}")

    def error_with_context(self, context: str, error: Exception):
        """Log error with context"""
        self.error(f"{context}: {type(error).__name__}: {error}", exc_info=True)


# Singleton
logger = NallyLogger()
