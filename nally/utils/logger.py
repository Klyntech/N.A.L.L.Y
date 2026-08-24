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


class _StructuredFormatter(logging.Formatter):
    """Formatter that appends extra fields as key=value pairs."""

    def format(self, record):
        msg = super().format(record)
        extras = {k: v for k, v in record.__dict__.items()
                  if k not in logging.LogRecord("", 0, "", 0, "", (), None).__dict__
                  and k not in ("message", "asctime")}
        if extras:
            pairs = " ".join(f"{k}={v}" for k, v in extras.items())
            return f"{msg} | {pairs}"
        return msg


# ── Global DNS/network spam filter (applies to all Nally processes) ──
import logging as _logging  # noqa: E402

class _DnsSpamFilter(_logging.Filter):
    """Collapse repeated DNS 11001 / WinError 1231/1236 to one WARNING per 30s."""
    _last_log = 0.0

    def filter(self, record: _logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        # Also inspect exc_info if present
        exc = ""
        if record.exc_info and record.exc_info[0] is not None:
            try:
                exc = str(record.exc_info[1])
            except Exception:
                exc = ""
        hay = f"{msg} {exc}"
        if "getaddrinfo failed" in hay or "11001" in hay or "WinError 1231" in hay or "WinError 1236" in hay:
            import time as _time
            now = _time.monotonic()
            if now - self._last_log < 30:
                return False
            self._last_log = now
            record.levelno = _logging.WARNING
            record.levelname = "WARNING"
            record.exc_info = None
            record.exc_text = None
            # Provide actionable one-liner
            record.msg = "Network DNS down (getaddrinfo 11001 / WinError 1231) — check internet, DNS (8.8.8.8), or proxy for api.telegram.org. Retrying…"
            record.args = ()
        return True

# Install globally once at import time
try:
    for _lname in (
        "telegram.ext._updater",
        "telegram.request",
        "telegram.request._httpxrequest",
        "httpx",
        "httpcore",
        "httpx._transports.default",
        "httpcore._async.connection_pool",
        "telethon.network.mtprotosender",
        "telethon.network.connection.connection",
    ):
        lg = _logging.getLogger(_lname)
        lg.addFilter(_DnsSpamFilter())
        if _lname.startswith("httpx") or _lname.startswith("httpcore"):
            lg.setLevel(_logging.WARNING)
        if _lname.startswith("telethon.network"):
            lg.setLevel(_logging.WARNING)
except Exception:
    pass


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
            file_handler.setFormatter(_StructuredFormatter("%(asctime)s | %(levelname)-8s | %(message)s"))
            self.logger.addHandler(file_handler)
        except Exception:
            # Log to console only if file logging fails
            self.logger.warning("Could not create log file, logging to console only")

    def debug(self, msg: str, **kwargs):
        self.logger.debug(msg, **kwargs)

    def info(self, msg: str, **kwargs):
        self.logger.info(msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        self.logger.warning(msg, **kwargs)

    def error(self, msg: str, exc_info: bool = False, **kwargs):
        self.logger.error(msg, exc_info=exc_info, **kwargs)

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
