"""Nally Configuration — single source of truth."""
import os
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"

def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

PROJECT_SCAN_DIRS = [str(Path.home() / "Desktop"), str(Path.home() / "Documents"), str(Path.home() / "Downloads")]

MCP_SERVERS = [
    {"name": "github", "url": "https://api.githubcopilot.com/mcp/", "transport": "http", "auth_mode": "oauth", "description": "GitHub repositories, issues, pull requests, and code search", "scope": "repo", "permission": "write"},
    {"name": "notion", "url": "https://mcp.notion.com/mcp", "transport": "http", "auth_mode": "oauth", "description": "Notion pages, databases, and content", "scope": "default", "permission": "write"},
    {"name": "gmail", "url": "https://gmailmcp.googleapis.com/mcp/v1", "transport": "http", "auth_mode": "oauth", "description": "Gmail MCP", "permission": "write"},
    {"name": "spotify", "url": os.getenv("SPOTIFY_MCP_URL", "https://mcp-gateway-external-pilot.spotify.net/mcp"), "transport": "http", "auth_mode": "oauth", "description": "Spotify MCP", "permission": "write"},
    {"name": "render", "url": "https://mcp.render.com/mcp", "transport": "http", "auth_mode": "api_key", "env_key": "RENDER_API_KEY", "description": "Render MCP", "permission": "write"},
]

PROVIDER = os.getenv("NALLY_PROVIDER", "openrouter").lower()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODELS = {"fast": "llama-3.3-70b-versatile", "balanced": "llama-3.3-70b-versatile", "powerful": "llama-3.3-70b-versatile", "frontier": "llama-3.3-70b-versatile"}

NIM_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
NIM_MODELS = {"fast": "nvidia/nemotron-3-super-120b-a12b", "balanced": "nvidia/nemotron-3-super-120b-a12b", "powerful": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "frontier": "nvidia/nemotron-3-super-120b-a12b"}

OPENCODE_API_KEY_RAW = os.getenv("OPENCODE_API_KEY", "")
OPENCODE_KEYS = [k.strip() for k in OPENCODE_API_KEY_RAW.split(",") if k.strip()]
OPENCODE_API_KEY = OPENCODE_KEYS[0] if OPENCODE_KEYS else ""
OPENCODE_BASE_URL = "https://opencode.ai/zen/v1"
OPENCODE_MODELS = {"fast": "muse-spark-1.2-contributor-free", "balanced": "muse-spark-1.2-contributor-free", "powerful": "muse-spark-1.2-contributor-free", "frontier": "muse-spark-1.2-contributor-free"}

OPENROUTER_API_KEY_RAW = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_KEYS = [k.strip() for k in OPENROUTER_API_KEY_RAW.split(",") if k.strip()]
OPENROUTER_API_KEY = OPENROUTER_KEYS[0] if OPENROUTER_KEYS else ""
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODELS = {
    # Free OpenRouter model (Nemotron lightning + optional reasoning)
    "fast": os.getenv("NALLY_MODEL_FAST", "nvidia/nemotron-3.5-lightning:free"),
    "balanced": os.getenv("NALLY_MODEL_BALANCED", "google/gemini-2.5-flash"),
    "powerful": os.getenv("NALLY_MODEL_POWERFUL", "anthropic/claude-sonnet-4"),
    "frontier": os.getenv("NALLY_MODEL_FRONTIER", "anthropic/claude-sonnet-4"),
}
# Enable OpenRouter reasoning payload for models that support it (e.g. nemotron-3.5-lightning)
OPENROUTER_REASONING = os.getenv("NALLY_OPENROUTER_REASONING", "true").lower() in ("1", "true", "yes")

SUBAGENT_MODELS = list(OPENCODE_MODELS.values())

if PROVIDER == "groq":
    API_KEY, BASE_URL, MODELS = GROQ_API_KEY, GROQ_BASE_URL, GROQ_MODELS
elif PROVIDER == "nim":
    API_KEY, BASE_URL, MODELS = NIM_API_KEY, NIM_BASE_URL, NIM_MODELS
elif PROVIDER in ("openrouter", "or"):
    PROVIDER = "openrouter"
    API_KEY, BASE_URL, MODELS = OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODELS
else:
    PROVIDER = "opencode"
    API_KEY, BASE_URL, MODELS = OPENCODE_API_KEY, OPENCODE_BASE_URL, OPENCODE_MODELS

ACTIVE_MODEL = os.getenv("NALLY_MODEL", "").strip() or MODELS["fast"]

HTTP_PROXY = os.getenv("HTTP_PROXY", "")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")
VERIFY_SSL = os.getenv("NALLY_VERIFY_SSL", "true").lower() not in ("false", "0", "no")
CA_BUNDLE = os.getenv("NALLY_CA_BUNDLE", "")

SESSION_ID = os.getenv("NALLY_SESSION", "default")
MAX_CONVERSATION_HISTORY = 50
CONTEXT_MAX_TOKENS = 500_000
CONTEXT_RECENT_MESSAGES = 10
CONTEXT_COMPRESSION_THRESHOLD = 20
CONTEXT_MAX_OUTPUT_TOKENS = 4096
MAX_MEMORIES_TO_INJECT = 12
MAX_TOOL_CALLS = int(os.getenv("NALLY_MAX_TOOL_CALLS", "50"))
MAX_ITERATIONS_PER_TURN = int(os.getenv("NALLY_MAX_ITERATIONS", "30"))
MAX_TOOL_OUTPUT = int(os.getenv("NALLY_MAX_TOOL_OUTPUT", "50000"))
MAX_AGENT_WALL_TIME = int(os.getenv("NALLY_MAX_AGENT_WALL_TIME", "300"))
RECURSION_LIMIT = int(os.getenv("NALLY_RECURSION_LIMIT", "50"))
DUPLICATE_TOOL_THRESHOLD = int(os.getenv("NALLY_DUPLICATE_TOOL_THRESHOLD", "3"))
DAILY_TOKEN_BUDGET = int(os.getenv("NALLY_DAILY_TOKEN_BUDGET", "0"))
MAX_SUBAGENT_DEPTH = int(os.getenv("NALLY_MAX_SUBAGENT_DEPTH", "4"))
TOOL_RETRY_LIMIT = int(os.getenv("NALLY_TOOL_RETRY_LIMIT", "3"))
MAX_TOOL_FAILURES_PER_TURN = int(os.getenv("NALLY_MAX_TOOL_FAILURES_PER_TURN", "5"))
TOKEN_WARN_THRESHOLD = float(os.getenv("NALLY_TOKEN_WARN_THRESHOLD", "0.95"))
APPROVAL_TIMEOUT = int(os.getenv("NALLY_APPROVAL_TIMEOUT", "1800"))

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000").split(",")
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_RPM = int(os.getenv("RATE_LIMIT_RPM", "30"))
RATE_LIMIT_BURST = int(os.getenv("RATE_LIMIT_BURST", "60"))

DATABASE_URL = os.getenv("DATABASE_URL", "")
TURSO_URL = os.getenv("TURSO_URL", "")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "")
NALLY_MEMORY_BACKEND = os.getenv("NALLY_MEMORY_BACKEND", "").strip().lower()

def memory_backend() -> str:
    live_backend = os.getenv("NALLY_MEMORY_BACKEND", "").strip().lower()
    if live_backend in ("postgres", "postgresql", "pg", "neon", "supabase"):
        return "postgres"
    if live_backend in ("sqlite", "local"):
        return "sqlite"
    if live_backend in ("turso", "libsql"):
        return "turso"
    url = (os.getenv("DATABASE_URL", "") or DATABASE_URL or "").strip().lower()
    if url.startswith("postgres://") or url.startswith("postgresql://"):
        return "postgres"
    if (os.getenv("TURSO_URL", "") or TURSO_URL) and (os.getenv("TURSO_TOKEN", "") or TURSO_TOKEN):
        return "turso"
    return "sqlite"

LAYERBASE_API_KEY = os.getenv("LAYERBASE_API_KEY", "")
LAYERBASE_DB_ID = os.getenv("LAYERBASE_DB_ID", "")
REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_TOKEN = os.getenv("REDIS_TOKEN", "")

PERSONALITIES = {
    "nally": {
        "name": "Nally",
        "tone": "quiet, sharp, informative",
        "style": "You are NALLY — a personal AI assistant. Tone: quiet, sharp, and informative. Telegram-first: brief replies. Use tools when needed. Never invent tool results. Never expose secrets.",
        "greeting": "Ready when you are.",
    },
}
ACTIVE_PERSONALITY = os.getenv("NALLY_PERSONALITY", "nally")

def get_system_prompt(personality=None, user_context=None, interface=None):
    from datetime import datetime
    p = PERSONALITIES.get(personality or ACTIVE_PERSONALITY, PERSONALITIES["nally"])
    prompt = p["style"]
    if user_context:
        prompt += f"\n\nKNOWN USER FACTS:\n{user_context}"
    now = datetime.now()
    prompt += f"\n\nCURRENT TIME CONTEXT:\n{now.strftime('%A, %B %d, %Y at %I:%M %p')} (WAT)"
    return prompt

_SYSTEM_PROMPT_CACHE = {}
def _resolve_system_prompt() -> str:
    if "value" not in _SYSTEM_PROMPT_CACHE:
        _SYSTEM_PROMPT_CACHE["value"] = get_system_prompt()
    return _SYSTEM_PROMPT_CACHE["value"]

def __getattr__(name: str):
    if name == "SYSTEM_PROMPT":
        return _resolve_system_prompt()
    raise AttributeError(name)

NALLY_ACCESS_TOKEN = os.getenv("NALLY_ACCESS_TOKEN", "")
NALLY_INTERNAL_TOKEN = os.getenv("NALLY_INTERNAL_TOKEN", "")
NALLY_BASE_URL = os.getenv("NALLY_BASE_URL", "").rstrip("/")
NALLY_CRED_KEY = os.getenv("NALLY_CRED_KEY", "")
NALLY_RECEIPT_KEY = os.getenv("NALLY_RECEIPT_KEY", "")
TELEGRAM_USER_ID = int(os.getenv("TELEGRAM_USER_ID", "0") or "0")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "")
TELEGRAM_MODE = os.getenv("TELEGRAM_MODE", "auto")
NALLY_VOICE_CALLS_ENABLED = os.getenv("NALLY_VOICE_CALLS_ENABLED", "false").lower() in ("1", "true", "yes")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
OTEL_METRICS_PORT = int(os.getenv("OTEL_METRICS_PORT", "8000") or "0")
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
NALLY_CURIOSITY_ENABLED = os.getenv("NALLY_CURIOSITY_ENABLED", "true").lower() in ("1", "true", "yes")
NALLY_CURIOSITY_INTERVAL = int(os.getenv("NALLY_CURIOSITY_INTERVAL", "21600"))
PORT = int(os.getenv("PORT", os.getenv("NALLY_PORT", "10000")))
NALLY_PORT = int(os.getenv("NALLY_PORT", str(PORT)))
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
RENDER_API_KEY = os.getenv("RENDER_API_KEY", "")
NALBRIDGE_MCP_TOKEN = os.getenv("NALBRIDGE_MCP_TOKEN", "")
NALLY_MCP_ALLOWED_HOSTS = os.getenv("NALLY_MCP_ALLOWED_HOSTS", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")

def resolve_telegram_mode() -> str:
    mode = (os.getenv("TELEGRAM_MODE") or TELEGRAM_MODE or "auto").strip().lower()
    if mode in ("polling", "webhook", "off"):
        return mode
    if TELEGRAM_WEBHOOK_URL or os.getenv("TELEGRAM_WEBHOOK_URL"):
        return "webhook"
    return "polling"

def validate_config(strict: bool = True):
    try:
        from nally.core.validator import validate_config as _validate
        return _validate(strict=strict)
    except Exception:
        return None
