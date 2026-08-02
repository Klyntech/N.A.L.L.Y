"""Nally LLM Client - Supports Groq and OpenCode with model routing"""

import json

from openai import OpenAI

from ..config import ACTIVE_MODEL, API_KEY, BASE_URL, PROVIDER
from ..utils.logger import logger


class NallyLLM:
    def __init__(self):
        self.client = None
        self.model = ACTIVE_MODEL
        self._initialized = False
        self._router = None

    def _get_router(self):
        if self._router is None:
            try:
                from ..router import model_router

                self._router = model_router
            except (ImportError, ModuleNotFoundError):
                self._router = None
        return self._router

    def _ensure_client(self):
        if not self._initialized:
            if not API_KEY:
                raise ValueError(
                    f"{PROVIDER.upper()}_API_KEY not set!\n"
                    "Groq: Get key at https://console.groq.com\n"
                    "OpenCode: Get key at https://opencode.ai/auth\n"
                    "Set it in .env file or environment variable."
                )

            kwargs = {
                "base_url": BASE_URL,
                "timeout": 60.0,
                "max_retries": 2,
                "api_key": API_KEY,
            }

            self.client = OpenAI(**kwargs)
            self._initialized = True
            logger.info(f"Connected to {PROVIDER.upper()} ({self.model})")

    def _select_model(self, messages: list, tools: list = None) -> str:
        """Use router to pick best model based on task"""
        router = self._get_router()
        if router and tools:
            # Extract user task from messages
            task = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    task = msg.get("content", "")
                    break
            if task:
                selected = router.select(task)
                return selected
        return self.model

    def chat(self, messages: list, tools: list = None, temperature: float = 0.7, cache_key: str = "default") -> dict:
        self._ensure_client()

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

        response = self.client.chat.completions.create(**kwargs)

        # Track actual token usage from API response
        if hasattr(response, "usage") and response.usage:
            try:
                from .context import context_manager

                context_manager.track_usage(response.usage.prompt_tokens, response.usage.completion_tokens)
            except Exception as e:
                logger.debug(f"Token tracking failed: {e}")

        return response

    def stream_chat(self, messages: list, temperature: float = 0.7, cache_key: str = "default"):
        self._ensure_client()

        model = self._select_model(messages)

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=2048,
            stream=True,
            extra_body={
                "prompt_cache_key": cache_key,
                "prompt_cache_retention": "24h",
            },
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
        self._ensure_client()
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

        response = self.client.chat.completions.create(**kwargs)

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
        self, model: str, messages: list, tools: list = None, temperature: float = 0.7, cache_key: str = "default"
    ) -> dict:
        """Chat with a specific model (bypasses routing)"""
        self._ensure_client()

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2048,
            "extra_body": {
                "prompt_cache_key": cache_key,
                "prompt_cache_retention": "24h",
            },
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        return self.client.chat.completions.create(**kwargs)


llm = NallyLLM()
