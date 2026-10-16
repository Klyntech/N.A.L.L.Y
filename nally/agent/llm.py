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

OPENCODE_FREE_MODELS = [
    "muse-spark-1.2-contributor-free",
    "mimo-v2.5-free",
    "nemotron-3.5-lightning-free",
    "big-pickle",
    "nemotron-3-ultra-free",
    "hy3-free",
    "laguna-s-2.1-free",
]

def _is_muse_spark(model: str) -> bool:
    return "muse-spark" in (model or "").lower()

NIM_MODELS_LIST = [
    "minimaxai/minimax-m3",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
]

OPENROUTER_MODELS_LIST = [
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemini-2.5-flash",
    "google/gemini-2.0-flash-001",
    "openai/gpt-4o-mini",
    "anthropic/claude-sonnet-4",
]

# NOTE: Full llm.py body restored in follow-up if truncated — see branch history.
# Minimal stub to keep imports working while full file is restored.

class NallyLLM:
    def __init__(self):
        self.model = ACTIVE_MODEL
        self._initialized = False
        self._keys = []
        self._clients = []
        self._active_idx = 0
        self._rotate_lock = threading.Lock()
        self._model_idx = 0
        self._failed_models = set()

    def _ensure_client(self):
        if self._initialized:
            return
        if PROVIDER == "opencode":
            from ..config import OPENCODE_KEYS
            self._keys = OPENCODE_KEYS if OPENCODE_KEYS else ([API_KEY] if API_KEY else [])
        elif PROVIDER == "openrouter":
            from ..config import OPENROUTER_KEYS
            self._keys = OPENROUTER_KEYS if OPENROUTER_KEYS else ([API_KEY] if API_KEY else [])
        else:
            self._keys = [API_KEY] if API_KEY else []
        if not self._keys:
            raise ValueError(f"{PROVIDER.upper()}_API_KEY not set")
        def _ssl_context():
            if not VERIFY_SSL:
                return False
            if CA_BUNDLE:
                return ssl.create_default_context(cafile=CA_BUNDLE)
            return True
        def _build(api_key, base_url):
            kwargs = {"base_url": base_url, "timeout": 60.0, "max_retries": 2, "api_key": api_key}
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
        self._clients = [_build(k, BASE_URL) for k in self._keys]
        self._active_idx = 0
        self._initialized = True
        logger.info(f"Connected to {PROVIDER.upper()} ({self.model}) with {len(self._keys)} key(s)")

    def _get_active_client(self):
        self._ensure_client()
        return self._clients[self._active_idx]

    def rotate_key(self):
        with self._rotate_lock:
            if len(self._clients) <= 1:
                return None
            self._active_idx = (self._active_idx + 1) % len(self._keys)
            return self._keys[self._active_idx][-6:]

    def _select_model(self, messages, tools=None):
        model = self.model
        if model in self._failed_models:
            fallback = OPENROUTER_MODELS_LIST if PROVIDER == "openrouter" else (NIM_MODELS_LIST if PROVIDER == "nim" else OPENCODE_FREE_MODELS)
            for m in fallback:
                if m not in self._failed_models:
                    return m
        return model

    def _is_rate_limit(self, exc):
        t = (str(exc) + str(getattr(exc, "__cause__", ""))).lower()
        return any(x in t for x in ["rate limit", "rate_limit", "429", "freeusagelimiterror"])

    def _is_model_not_found(self, exc):
        t = (str(exc) + str(getattr(exc, "__cause__", ""))).lower()
        return any(x in t for x in ["modelerror", "model is not supported", "model not found", "unknown model"])

    def _next_fallback_model(self, current):
        if PROVIDER == "nim":
            model_list = NIM_MODELS_LIST
        elif PROVIDER == "openrouter":
            model_list = OPENROUTER_MODELS_LIST
        elif PROVIDER == "opencode":
            model_list = OPENCODE_FREE_MODELS
        else:
            return None
        self._failed_models.add(current)
        try:
            start = model_list.index(current)
        except ValueError:
            start = self._model_idx
        for i in range(len(model_list)):
            idx = (start + 1 + i) % len(model_list)
            m = model_list[idx]
            if m not in self._failed_models:
                self._model_idx = idx
                return m
        return None

    def _create_completion(self, kwargs):
        model = kwargs.get("model")
        last_exc = None
        while True:
            try:
                if PROVIDER in ("nim", "openrouter", "groq"):
                    eb = dict(kwargs.get("extra_body") or {})
                    eb.pop("prompt_cache_key", None)
                    eb.pop("prompt_cache_retention", None)
                    if PROVIDER == "openrouter":
                        mn = (kwargs.get("model") or "").lower()
                        if any(x in mn for x in ("lightning", "reasoning", "nemotron-3.5")):
                            try:
                                from ..config import OPENROUTER_REASONING
                            except Exception:
                                OPENROUTER_REASONING = True
                            if OPENROUTER_REASONING and "reasoning" not in eb:
                                eb["reasoning"] = {"enabled": True}
                    if eb:
                        kwargs["extra_body"] = eb
                    else:
                        kwargs.pop("extra_body", None)
                result = self._get_active_client().chat.completions.create(**kwargs)
                self._failed_models.discard(model)
                return result
            except Exception as e:
                if self._is_rate_limit(e) or self._is_model_not_found(e) or ("500" in str(e).lower() and "internal" in str(e).lower()):
                    nxt = self._next_fallback_model(model)
                    if nxt:
                        logger.warning(f"Model {model} failed; falling back to {nxt}")
                        model = nxt
                        kwargs["model"] = model
                        last_exc = e
                        continue
                    last_exc = e
                    break
                raise
        raise last_exc

    def chat(self, messages, tools=None, temperature=0.7, cache_key="default", max_tokens=4096):
        self._get_active_client()
        model = self._select_model(messages, tools)
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "extra_body": {"prompt_cache_key": cache_key, "prompt_cache_retention": "24h"},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = self._create_completion(kwargs)
        if hasattr(response, "usage") and response.usage:
            try:
                from .context import context_manager
                context_manager.track_usage(response.usage.prompt_tokens, response.usage.completion_tokens)
            except Exception:
                pass
        return response

    def stream_chat(self, messages, temperature=0.7, cache_key="default"):
        model = self._select_model(messages)
        response = self._create_completion({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2048,
            "stream": True,
            "extra_body": {"prompt_cache_key": cache_key, "prompt_cache_retention": "24h"},
        })
        for chunk in response:
            if chunk and chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def stream_chat_with_tools(self, messages, tools=None, temperature=0.7, cache_key="default"):
        model = self._select_model(messages, tools)
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4096,
            "stream": True,
            "extra_body": {"prompt_cache_key": cache_key, "prompt_cache_retention": "24h"},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = self._create_completion(kwargs)
        for chunk in response:
            if not chunk or not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield {"type": "content", "text": delta.content}
            if getattr(delta, "tool_calls", None):
                for tc in delta.tool_calls:
                    yield {
                        "type": "tool_call",
                        "id": getattr(tc, "id", "") or "",
                        "name": getattr(getattr(tc, "function", None), "name", "") or "",
                        "args": getattr(getattr(tc, "function", None), "arguments", "") or "",
                    }

    def simple_chat(self, user_message, system_prompt=None):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})
        return self.chat(messages).choices[0].message.content

    def stream_simple_chat(self, user_message, system_prompt=None):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})
        return self.stream_chat(messages)

    def chat_with_model(self, model, messages, tools=None, temperature=0.7, cache_key="default", max_tokens=2048):
        self._get_active_client()
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "extra_body": {"prompt_cache_key": cache_key, "prompt_cache_retention": "24h"},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return self._create_completion(kwargs)

llm = NallyLLM()

def call_llm(messages, temperature=0.7):
    return llm.chat(messages=messages, temperature=temperature).choices[0].message.content
