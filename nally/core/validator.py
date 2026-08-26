"""Nally Configuration Validator — validates env vars on startup.

Call validate_config() after loading .env to catch misconfigurations
before the server starts. Returns a list of errors, raises ConfigError
if any critical ones are found.
"""

import os
from pathlib import Path
from typing import List, Tuple

from .errors import ConfigError


def _ensure_env_loaded():
    """Load .env if not already loaded."""
    from dotenv import load_dotenv

    # Check if .env exists in project root
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)  # Don't override existing env vars


def validate_config(strict: bool = True) -> List[Tuple[str, str, str]]:
    """Validate all configuration variables.

    Args:
        strict: If True, raise ConfigError on critical failures.
                If False, return errors without raising.

    Returns:
        List of (level, key, message) tuples.
        level is "error" or "warning".
    """
    _ensure_env_loaded()
    errors: List[Tuple[str, str, str]] = []

    def _error(key: str, msg: str):
        errors.append(("error", key, msg))

    def _warning(key: str, msg: str):
        errors.append(("warning", key, msg))

    # ── Required vars ──────────────────────────────────────

    access_token = os.getenv("NALLY_ACCESS_TOKEN", "")
    if not access_token:
        _error("NALLY_ACCESS_TOKEN", "Required for API auth. Server won't start without it.")
    elif len(access_token) < 8:
        _warning("NALLY_ACCESS_TOKEN", "Token is very short. Consider a longer, random value.")

    # ── LLM provider ──────────────────────────────────────

    provider = os.getenv("NALLY_PROVIDER", "opencode").lower()
    if provider not in ("opencode", "groq", "nim"):
        _error("NALLY_PROVIDER", f"Invalid provider '{provider}'. Must be 'opencode', 'groq', or 'nim'.")

    if provider == "opencode":
        api_key = os.getenv("OPENCODE_API_KEY", "")
        if not api_key:
            _error("OPENCODE_API_KEY", "Required when NALLY_PROVIDER=opencode.")
        elif not api_key.startswith("sk-"):
            _warning("OPENCODE_API_KEY", "Key doesn't start with 'sk-'. Verify it's correct.")
    elif provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            _error("GROQ_API_KEY", "Required when NALLY_PROVIDER=groq.")
        elif not api_key.startswith("gsk_"):
            _warning("GROQ_API_KEY", "Key doesn't start with 'gsk_'. Verify it's correct.")
    elif provider == "nim":
        api_key = os.getenv("NVIDIA_API_KEY", "")
        if not api_key:
            _error("NVIDIA_API_KEY", "Required when NALLY_PROVIDER=nim.")
        elif not api_key.startswith("nvapi-"):
            _warning("NVIDIA_API_KEY", "Key doesn't start with 'nvapi-'. Verify it's correct.")

    # ── Port ───────────────────────────────────────────────

    port_str = os.getenv("PORT", "5000")
    try:
        port = int(port_str)
        if port < 1024 or port > 65535:
            _error("PORT", f"Port {port} out of range. Must be 1024-65535.")
    except ValueError:
        _error("PORT", f"Invalid port value: '{port_str}'. Must be an integer.")

    # ── Optional dependencies ──────────────────────────────
    # Warn about missing optional packages so users know what to install.

    optional_deps = [
        ("psutil", "psutil", "system_health tool (CPU/memory/disk monitoring)"),
        ("duckduckgo_search", "duckduckgo-search", "web search fallback (DuckDuckGo)"),
        ("pytesseract", "pytesseract", "OCR in vision analysis"),
        ("readability", "readability-lxml", "better article extraction in fetch tool"),
        ("PIL", "Pillow", "image generation and editing"),
    ]
    for module_name, pip_name, feature in optional_deps:
        try:
            __import__(module_name)
        except ImportError:
            _warning("DEPENDENCIES", f"Optional: {pip_name} not installed — needed for {feature}")

    # ── Database (optional) ────────────────────────────────

    database_url = os.getenv("DATABASE_URL", "")
    if database_url:
        if database_url.startswith("postgresql://") or database_url.startswith("postgres://"):
            # PostgreSQL — check for asyncpg driver
            try:
                import asyncpg  # noqa: F401
            except ImportError:
                _warning("DATABASE_URL", "PostgreSQL URL set but asyncpg not installed. Run: pip install asyncpg")
        elif not os.path.isabs(database_url) and not database_url.startswith("libsql://"):
            _warning("DATABASE_URL", f"Unusual URL format: {database_url[:50]}...")

    # ── Redis (optional) ───────────────────────────────────

    redis_url = os.getenv("REDIS_URL", "")
    if redis_url:
        if not redis_url.startswith(("redis://", "rediss://")):
            _warning("REDIS_URL", f"Unusual Redis URL format: {redis_url[:50]}...")

    # ── Rate limiting ──────────────────────────────────────

    rpm_str = os.getenv("RATE_LIMIT_RPM", "30")
    try:
        rpm = int(rpm_str)
        if rpm < 1:
            _warning("RATE_LIMIT_RPM", f"Rate limit RPM is {rpm}. Set to at least 1.")
    except ValueError:
        _error("RATE_LIMIT_RPM", f"Invalid value: '{rpm_str}'. Must be an integer.")

    burst_str = os.getenv("RATE_LIMIT_BURST", "60")
    try:
        burst = int(burst_str)
        if burst < 1:
            _warning("RATE_LIMIT_BURST", f"Rate limit burst is {burst}. Set to at least 1.")
    except ValueError:
        _error("RATE_LIMIT_BURST", f"Invalid value: '{burst_str}'. Must be an integer.")

    # ── CORS ───────────────────────────────────────────────

    origins = os.getenv("ALLOWED_ORIGINS", "")
    if origins:
        for origin in origins.split(","):
            origin = origin.strip()
            if origin and not origin.startswith(("http://", "https://")):
                _warning("ALLOWED_ORIGINS", f"Origin doesn't start with http(s)://: {origin}")

    # ── Telegram (optional) ────────────────────────────────

    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if telegram_token:
        parts = telegram_token.split(":")
        if len(parts) != 2 or not parts[0].isdigit():
            _warning("TELEGRAM_BOT_TOKEN", "Token format looks wrong. Expected: '123456:ABC-DEF'")

    # ── Raise on critical errors ───────────────────────────

    critical = [e for e in errors if e[0] == "error"]
    if strict and critical:
        msg = "\n".join(f"  {key}: {msg}" for _, key, msg in critical)
        raise ConfigError(
            message=f"Configuration errors found:\n{msg}",
            code="config_validation_failed",
        )

    return errors


def print_validation_report(errors: List[Tuple[str, str, str]]):
    """Print a formatted validation report."""
    if not errors:
        print("  Config: all checks passed")
        return

    print("\n  Config Validation Report:")
    print("  " + "-" * 40)

    for level, key, msg in errors:
        icon = "ERROR" if level == "error" else "WARN "
        print(f"  [{icon}] {key}: {msg}")

    print()
