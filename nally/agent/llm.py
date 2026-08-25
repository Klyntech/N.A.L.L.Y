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

# OpenCode free models in fallback order (fastest first) — Muse Spark 1.2 Contributor Free is primary
OPENCODE_FREE_MODELS = [
    "muse-spark-1.2-contributor-free",
    "hy3-free",
    "nemotron-3.5-lightning-free",
    "nemotron-3-ultra-free",
    "ling-3.0-flash-free",
    "laguna-s-2.1-free",
]

def _is_muse_spark(model: str) -> bool:
    return "muse-spark" in (model or "").lower()


def _chat_tools_to_responses_tools(tools: list | None) -> list | None:
    """Convert chat.completions tools (type/function wrapper) to responses tools (flat)."""
    if not tools:
        return None
    out = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        # Already flat responses style?
        if t.get("type") == "function" and "name" in t and "function" not in t:
            out.append(t)
            continue
        # Chat style: {type: function, function: {name, description, parameters}}
        fn = t.get("function") or {}
        name = fn.get("name") or t.get("name")
        if not name:
            continue
        item = {"type": "function", "name": name}
        if fn.get("description"):
            item["description"] = fn["description"]
        if fn.get("parameters"):
            item["parameters"] = fn["parameters"]
        elif t.get("parameters"):
            item["parameters"] = t["parameters"]
        out.append(item)
    return out if out else None


def _openai_messages_to_responses(messages: list) -> tuple[str | None, list]:
    """Split OpenAI chat messages into (instructions, input_list) for responses API."""
    instructions_parts = []
    input_list = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "system":
            if isinstance(content, list):
                # multimodal system? join texts
                txt = " ".join(c.get("text","") for c in content if isinstance(c, dict))
                instructions_parts.append(txt)
            elif content:
                instructions_parts.append(str(content))
        elif role == "user":
            # Handle multimodal content (list with text + image_url) — convert to responses format
            if isinstance(content, list):
                converted = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type")
                    if ptype == "text":
                        converted.append({"type": "input_text", "text": part.get("text", "")})
                    elif ptype == "image_url":
                        # chat format: {"type":"image_url","image_url":{"url":"data:..."}}
                        url = part.get("image_url")
                        if isinstance(url, dict):
                            url = url.get("url", "")
                        if url:
                            converted.append({"type": "input_image", "image_url": url})
                    elif ptype == "input_text":
                        converted.append({"type": "input_text", "text": part.get("text", "")})
                    elif ptype == "input_image":
                        # already responses format
                        img_url = part.get("image_url")
                        if img_url:
                            converted.append({"type": "input_image", "image_url": img_url})
                    elif part.get("text"):
                        converted.append({"type": "input_text", "text": part.get("text","")})
                # If conversion produced nothing, fallback to string
                if converted:
                    input_list.append({"role": "user", "content": converted})
                else:
                    input_list.append({"role": "user", "content": str(content)})
            else:
                input_list.append({"role": "user", "content": str(content) if content is not None else ""})
        elif role == "assistant":
            # Content
            tool_calls = m.get("tool_calls")
            if content:
                # Responses history: assistant messages can be represented as role assistant
                # but for tool-call history we also need function_call items.
                # We add a message item first, then function_calls separately below.
                # If there's no tool_calls, just a single assistant message.
                if not tool_calls:
                    input_list.append({"role": "assistant", "content": str(content)})
                else:
                    # Add commentary as assistant message if non-empty, then function_calls
                    if str(content).strip():
                        input_list.append({"role": "assistant", "content": str(content)})
            if tool_calls:
                for tc in tool_calls:
                    # tc can be dict with id/name/args or object
                    if isinstance(tc, dict):
                        tc_id = tc.get("id", "")
                        tc_name = tc.get("name") or tc.get("function", {}).get("name", "")
                        tc_args = tc.get("args") or tc.get("function", {}).get("arguments", "")
                        if isinstance(tc_args, dict):
                            tc_args = json.dumps(tc_args)
                    else:
                        tc_id = getattr(tc, "id", "")
                        tc_name = getattr(getattr(tc, "function", None), "name", "") or getattr(tc, "name", "")
                        tc_args = getattr(getattr(tc, "function", None), "arguments", "") or ""
                        if isinstance(tc_args, dict):
                            tc_args = json.dumps(tc_args)
                    if tc_name:
                        input_list.append({
                            "type": "function_call",
                            "call_id": tc_id,
                            "name": tc_name,
                            "arguments": tc_args if isinstance(tc_args, str) else json.dumps(tc_args),
                        })
        elif role == "tool":
            # Tool output -> function_call_output
            tool_call_id = m.get("tool_call_id", "")
            # responses expects call_id
            input_list.append({
                "type": "function_call_output",
                "call_id": tool_call_id,
                "output": str(content) if content is not None else "",
            })
        else:
            # Fallback: treat as user
            input_list.append({"role": role, "content": str(content) if content is not None else ""})
    instructions = "\n\n".join(instructions_parts) if instructions_parts else None
    # If input_list is single user string, responses also accepts plain string; keep list for uniformity
    return instructions, input_list


def _responses_to_chat_completion(resp):
    """Wrap a Responses API response into a ChatCompletion-like object for Nally's graph."""
    from openai.types.chat import ChatCompletion, ChatCompletionMessage
    from openai.types.chat.chat_completion import Choice
    from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall, Function

    # Extract text — output_text is the aggregated final assistant text
    text = getattr(resp, "output_text", None) or ""
    # Fallback: collect from output messages
    if not text:
        parts = []
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", None) == "message" and getattr(item, "content", None):
                for c in item.content:
                    if getattr(c, "type", None) == "output_text" and getattr(c, "text", None):
                        parts.append(c.text)
        text = "".join(parts)

    # Extract tool calls
    tool_calls = []
    for item in getattr(resp, "output", []) or []:
        if getattr(item, "type", None) == "function_call":
            name = getattr(item, "name", "") or ""
            args = getattr(item, "arguments", "") or "{}"
            call_id = getattr(item, "call_id", "") or getattr(item, "id", "") or f"call_{len(tool_calls)}"
            if not name:
                continue
            # Ensure args is string JSON
            if not isinstance(args, str):
                try:
                    args = json.dumps(args)
                except Exception:
                    args = "{}"
            tool_calls.append(
                ChatCompletionMessageToolCall(
                    id=call_id,
                    type="function",
                    function=Function(name=name, arguments=args),
                )
            )

    # Build ChatCompletionMessage
    msg_kwargs = {"role": "assistant", "content": text or ""}
    if tool_calls:
        msg_kwargs["tool_calls"] = tool_calls

    # Usage mapping — responses has input_tokens/output_tokens
    # ChatCompletion expects usage but we handle tracking separately
    message = ChatCompletionMessage(**msg_kwargs)
    choice = Choice(finish_reason="tool_calls" if tool_calls else "stop", index=0, message=message)
    # Construct minimal ChatCompletion
    # We need to provide id, created, model, object — use resp fields where possible
    chat_resp = ChatCompletion(
        id=getattr(resp, "id", "resp"),
        choices=[choice],
        created=int(getattr(resp, "created_at", 0) or 0),
        model=getattr(resp, "model", "muse-spark-1.2-contributor-free"),
        object="chat.completion",
    )
    # Attach usage for tracking if present — mimic chat usage shape
    usage = getattr(resp, "usage", None)
    if usage:
        # Create a simple object with prompt_tokens/completion_tokens for context_manager
        class _Usage:
            pass
        u = _Usage()
        u.prompt_tokens = getattr(usage, "input_tokens", 0) or 0
        u.completion_tokens = getattr(usage, "output_tokens", 0) or 0
        u.total_tokens = getattr(usage, "total_tokens", 0) or (u.prompt_tokens + u.completion_tokens)
        chat_resp.usage = u  # type: ignore
    return chat_resp


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

    def _create_via_responses(self, kwargs: dict):
        """Call responses.create for Muse Spark and wrap to ChatCompletion."""
        model = kwargs.get("model")
        messages = kwargs.get("messages", [])
        tools = kwargs.get("tools")
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 4096)
        extra_body = kwargs.get("extra_body", {}) or {}
        cache_key = extra_body.get("prompt_cache_key", "default")

        instructions, input_list = _openai_messages_to_responses(messages)
        # Responses API expects input as list or string; use list for fidelity
        # If single user string and no history, we can keep string, but list works too
        # Ensure input_list is not empty
        if not input_list:
            input_list = [{"role": "user", "content": "Hello"}]

        resp_tools = _chat_tools_to_responses_tools(tools)

        # Build responses kwargs — map max_tokens -> max_output_tokens
        # Muse Spark reasoning can be heavy; ensure at least 512 for reasoning, 2000 for vision
        max_out = max(512, max_tokens)
        # If input contains image, bump to 2500 to allow reasoning + vision output (1200 was incomplete in tests)
        try:
            has_image = any(
                isinstance(item.get("content"), list) and any(p.get("type") == "input_image" for p in item["content"])
                for item in input_list if isinstance(item, dict)
            )
            if has_image:
                max_out = max(max_out, 2500)
        except Exception:
            pass

        r_kwargs = {
            "model": model,
            "max_output_tokens": max_out,
            "temperature": temperature,
        }
        if instructions:
            r_kwargs["instructions"] = instructions
        # input must be list for history fidelity; single item can be string but list is safer
        r_kwargs["input"] = input_list
        if resp_tools:
            r_kwargs["tools"] = resp_tools
            r_kwargs["tool_choice"] = kwargs.get("tool_choice", "auto")
        # Preserve prompt caching
        if cache_key:
            r_kwargs["prompt_cache_key"] = cache_key
            r_kwargs["prompt_cache_retention"] = extra_body.get("prompt_cache_retention", "24h")

        # For reasoning models, OpenCode expects reasoning.effort via extra_body? Pi shows thinkingLevelMap.
        # Muse Spark is high-effort by default; we don't override.

        client = self._get_active_client()
        resp = client.responses.create(**r_kwargs)
        return _responses_to_chat_completion(resp)

    def _create_completion(self, kwargs: dict):
        """Call chat.completions.create with automatic model fallback on rate limits.

        Muse Spark models are routed via responses API (their native endpoint).
        On a detected rate-limit error, rotates to the next healthy model in
        OPENCODE_FREE_MODELS and retries. Clears the model from the failed set
        on success so it can be retried in a later request.
        """
        model = kwargs.get("model")
        last_exc = None
        while True:
            try:
                if _is_muse_spark(model):
                    result = self._create_via_responses(kwargs)
                else:
                    result = self._get_active_client().chat.completions.create(**kwargs)
                self._failed_models.discard(model)
                return result
            except Exception as e:
                # If muse-spark via responses fails with 500 internal, treat as fallback-eligible too
                err_str = str(e).lower()
                is_internal_500 = "500" in err_str and "internal server error" in err_str
                if self._is_rate_limit(e) or is_internal_500:
                    next_model = self._next_fallback_model(model)
                    if next_model:
                        logger.warning(
                            f"Model {model} failed ({type(e).__name__}: {str(e)[:120]}); falling back to {next_model}"
                        )
                        model = next_model
                        kwargs["model"] = model
                        last_exc = e
                        continue
                    last_exc = e
                    break
                raise
        logger.error(f"All OpenCode free models rate-limited/failed (last: {last_exc})")
        raise last_exc

    def chat(self, messages: list, tools: list = None, temperature: float = 0.7, cache_key: str = "default", max_tokens: int = 4096) -> dict:
        client = self._get_active_client()

        # Route to best model for this task
        model = self._select_model(messages, tools)
        if model != self.model:
            logger.debug(f"Routed to {model} for this request")

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
        # Muse Spark uses responses API which doesn't support chat streaming — emulate via single response
        if _is_muse_spark(model):
            resp = self.chat(messages, temperature=temperature, cache_key=cache_key, max_tokens=2048)
            text = resp.choices[0].message.content or ""
            # Yield in small chunks to preserve streaming UX
            if text:
                # Split into ~50 char chunks
                for i in range(0, len(text), 80):
                    yield text[i:i+80]
            return

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
            if not chunk or not chunk.choices:
                continue
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
        # Muse Spark via responses doesn't support chat streaming — emulate
        if _is_muse_spark(model):
            resp = self.chat(messages, tools=tools, temperature=temperature, cache_key=cache_key, max_tokens=16384 if tools else 4096)
            msg = resp.choices[0].message
            if msg.content:
                yield {"type": "content", "text": msg.content}
            if getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    # tc can be ChatCompletionMessageToolCall
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except Exception:
                        args = {}
                    yield {"type": "tool_call", "id": tc.id, "name": tc.function.name, "args": args}
            return

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
        # Muse Spark requires responses API
        if _is_muse_spark(model):
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
            return self._create_via_responses(kwargs)

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


def call_llm(messages: list, temperature: float = 0.7) -> str:
    """Back-compat shim used by the post-response self-correction path.

    graph.py imports `call_llm` and expects it to accept an OpenAI-style
    `messages` list plus `temperature` and return the assistant text. The
    real client is the `llm` singleton above.
    """
    return llm.chat(messages=messages, temperature=temperature).choices[0].message.content
