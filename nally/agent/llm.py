"""Nally LLM Client - Supports Groq and OpenCode with model routing + multi-key rotation"""

import json
import ssl
import threading

import httpx
from openai import OpenAI

from ..config import (
    ACTIVE_MODEL,
    API_KEY,
    BASE_URL,
    CA_BUNDLE,
    HTTP_PROXY,
    HTTPS_PROXY,
    PROVIDER,
    VERIFY_SSL,
)
from ..utils.logger import logger

# OpenCode free models in fallback order (fastest first)
OPENCODE_FREE_MODELS = [
    "hy3-free",
    "nemotron-3.5-lightning-free",
    "nemotron-3-ultra-free",
    "ling-3.0-tiny-free",
    "laguna-s-2.1-free",
]

# Rate limit error signatures
_RATE_LIMIT_INDICATORS = [
    "FreeUsageLimitError",
    "rate limit",
    "rate_limit",
    "429",
]


def _ssl_context() -> ssl.SSLContext | bool:
    """Build SSL context based on config.

    Returns:
        ssl.SSLContext with custom CA bundle if NALLY_CA_BUNDLE is set,
        False if VERIFY_SSL is disabled,
        True otherwise (default verification).
    """
    if not VERIFY_SSL:
        return False
    if CA_BUNDLE:
        ctx = ssl.create_default_context(cafile=CA_BUNDLE)
        return ctx
    return True


def _build_client(api_key: str, base_url: str) -> OpenAI:
    """Build an OpenAI client with proxy/SSL settings."""
    kwargs = {
        "base_url": base_url,
        "timeout": 60.0,
        "max_retries": 2,
        "api_key": api_key,
    }
    if HTTPS_PROXY or HTTP_PROXY:
        proxies = {}
        if HTTP_PROXY:
            proxies["http://"] = HTTP_PROXY
        if HTTPS_PROXY:
            proxies["https://"] = HTTPS_PROXY
        kwargs["http_client"] = httpx.Client(proxies=proxies, verify=_ssl_context())
    elif not VERIFY_SSL or CA_BUNDLE:
        kwargs["http_client"] = httpx.Client(verify=_ssl_context())
    return OpenAI(**kwargs)


class NallyLLM:
    def __init__(self):
        self.model = ACTIVE_MODEL
        self._initialized = False

        # Multi-key rotation
        self._keys: list[str] = []
        self._clients: list[OpenAI] = []
        self._active_idx: int = 0
        self._rotate_lock = threading.Lock()

        # Model fallback tracking
        self._model_idx: int = 0
        self._failed_models: set = set()

    def _ensure_client(self):
        if self._initialized:
            return

        if PROVIDER == "opencode":
            from ..config import OPENCODE_KEYS

            self._keys = OPENCODE_KEYS if OPENCODE_KEYS else ([API_KEY] if API_KEY else [])
        else:
            self._keys = [API_KEY] if API_KEY else []

        if not self._keys:
            raise ValueError(
                f"{PROVIDER.upper()}_API_KEY not set!\n"
                "Groq: Get key at https://console.groq.com\n"
                "OpenCode: Get key at https://opencode.ai/auth\n"
                "Set it in .env file or environment variable.\n"
                "Multiple keys: OPENCODE_API_KEY=sk-abc,sk-def"
            )

        self._clients = [_build_client(k, BASE_URL) for k in self._keys]
        self._active_idx = 0
        self._initialized = True
        logger.info(
            f"Connected to {PROVIDER.upper()} ({self.model}) "
            f"with {len(self._keys)} key(s)"
        )

    def _get_active_client(self) -> OpenAI:
        """Return the current active client (thread-safe index read)."""
        self._ensure_client()
        return self._clients[self._active_idx]

    def rotate_key(self) -> str | None:
        """Rotate to the next API key. Returns the new key suffix, or None if exhausted."""
        with self._rotate_lock:
            if len(self._clients) <= 1:
                return None
            old_idx = self._active_idx
            self._active_idx = (self._active_idx + 1) % len(self._keys)
            new_key = self._keys[self._active_idx]
            suffix = new_key[-6:] if len(new_key) > 6 else new_key
            logger.warning(
                f"Key rotation: {old_idx + 1}/{len(self._keys)} -> "
                f"{self._active_idx + 1}/{len(self._keys)} (..{suffix})"
            )
            return suffix

    def _select_model(self, messages: list, tools: list = None) -> str:
        """Return the active model, honoring the fallback state."""
        model = self.model

        # If the selected model is known-failed (rate-limited) and we have
        # alternatives, jump straight to the first healthy fallback model.
        if (
            PROVIDER == "opencode"
            and OPENCODE_FREE_MODELS
            and model in self._failed_models
        ):
            for m in OPENCODE_FREE_MODELS:
                if m not in self._failed_models:
                    logger.debug(f"Skipping failed model {model}; using {m}")
                    model = m
                    break
        return model

    def _is_rate_limit(self, exc: Exception) -> bool:
        """Detect rate-limit / free-tier exhaustion errors from OpenCode."""
        text = str(exc).lower()
        cause = str(getattr(exc, "__cause__", "")).lower()
        combined = f"{text} {cause}"
        return any(ind.lower() in combined for ind in _RATE_LIMIT_INDICATORS)

    def _next_fallback_model(self, current: str) -> str | None:
        """Return the next healthy model to try after `current` failed.

        Marks `current` as failed and cycles through OPENCODE_FREE_MODELS,
        skipping already-failed models. Returns None if all are exhausted.
        Only meaningful for the OpenCode provider.
        """
        if PROVIDER != "opencode" or not OPENCODE_FREE_MODELS:
            return None
        self._failed_models.add(current)
        try:
            start = OPENCODE_FREE_MODELS.index(current)
        except ValueError:
            start = self._model_idx
        for i in range(len(OPENCODE_FREE_MODELS)):
            idx = (start + 1 + i) % len(OPENCODE_FREE_MODELS)
            m = OPENCODE_FREE_MODELS[idx]
            if m not in self._failed_models:
                self._model_idx = idx
                return m
        return None

    def _create_completion(self, kwargs: dict):
        """Call chat.completions.create with automatic model fallback on rate limits.

        On a detected rate-limit error, rotates to the next healthy model in
        OPENCODE_FREE_MODELS and retries. Clears the model from the failed set
        on success so it can be retried in a later request.
        """
        model = kwargs.get("model")
        last_exc = None
        while True:
            try:
                result = self._get_active_client().chat.completions.create(**kwargs)
                self._failed_models.discard(model)
                return result
            except Exception as e:
                if self._is_rate_limit(e):
                    next_model = self._next_fallback_model(model)
                    if next_model:
                        logger.warning(
                            f"Model {model} rate-limited; falling back to {next_model}"
                        )
                        model = next_model
                        kwargs["model"] = model
                        last_exc = e
                        continue
                    last_exc = e
                    break
                raise
        logger.error(f"All OpenCode free models rate-limited (last: {last_exc})")
        raise last_exc

    def chat(self, messages: list, tools: list = None, temperature: float = 0.7, cache_key: str = "default") -> dict:
        client = self._get_active_client()

        # Route to best model for this task
        model = self._select_model(messages, tools)
        if model != self.model:
            logger.debug(f"Routed to {model} for this request")

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4096,
            "extra_body": {
                "prompt_cache_key": cache_key,
                "prompt_cache_retention": "24h",
            },
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self._create_completion(kwargs)

        # Track actual token usage from API response
        if hasattr(response, "usage") and response.usage:
            try:
                from .context import context_manager

                context_manager.track_usage(response.usage.prompt_tokens, response.usage.completion_tokens)
            except Exception as e:
                logger.debug(f"Token tracking failed: {e}")

        return response

    def stream_chat(self, messages: list, temperature: float = 0.7, cache_key: str = "default"):
        model = self._select_model(messages)

        response = self._create_completion(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 2048,
                "stream": True,
                "extra_body": {
                    "prompt_cache_key": cache_key,
                    "prompt_cache_retention": "24h",
                },
            }
        )

        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def stream_chat_with_tools(
        self, messages: list, tools: list = None, temperature: float = 0.7, cache_key: str = "default"
    ):
        """Stream chat with tool support. Yields dicts:
        {'type': 'content', 'text': '...'} for text chunks
        {'type': 'tool_call', 'id': '...', 'name': '...', 'args': {...}} for tool calls
        """
        model = self._select_model(messages, tools)

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 16384 if tools else 4096,
            "stream": True,
            "extra_body": {
                "prompt_cache_key": cache_key,
                "prompt_cache_retention": "24h",
            },
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self._create_completion(kwargs)

        # Track tool call state across chunks
        tool_calls = {}  # index -> {id, name, args_str}

        for chunk in response:
            try:
                delta = chunk.choices[0].delta if chunk and chunk.choices else None
                if not delta:
                    continue

                # Content text chunk
                if delta.content:
                    yield {"type": "content", "text": delta.content}

                # Tool call chunks
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        if not tc:
                            continue
                        idx = tc.index if hasattr(tc, "index") and tc.index is not None else 0
                        if idx not in tool_calls:
                            tool_calls[idx] = {"id": "", "name": "", "args_str": ""}
                        if tc.id:
                            tool_calls[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls[idx]["args_str"] += tc.function.arguments
            except Exception as e:
                logger.debug(f"Streaming chunk processing failed: {e}")
                continue

        # Yield completed tool calls
        for idx in sorted(tool_calls.keys()):
            tc = tool_calls[idx]
            if not tc["name"]:
                continue
            try:
                args = json.loads(tc["args_str"]) if tc["args_str"] else {}
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Tool call args parse failed for '{tc['name']}': {e} (args_str={tc['args_str'][:200]})")
                args = {}
            yield {"type": "tool_call", "id": tc["id"], "name": tc["name"], "args": args}

    def simple_chat(self, user_message: str, system_prompt: str = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        response = self.chat(messages)
        return response.choices[0].message.content

    def stream_simple_chat(self, user_message: str, system_prompt: str = None):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        return self.stream_chat(messages)

    def chat_with_model(
        self, model: str, messages: list, tools: list = None, temperature: float = 0.7, cache_key: str = "default", max_tokens: int = 2048
    ) -> dict:
        """Chat with a specific model (bypasses routing)"""
        client = self._get_active_client()

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "extra_body": {
                "prompt_cache_key": cache_key,
                "prompt_cache_retention": "24h",
            },
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        return client.chat.completions.create(**kwargs)


llm = NallyLLM()
