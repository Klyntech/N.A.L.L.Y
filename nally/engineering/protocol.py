"""LLM backend abstraction.

The engineering loop NEVER calls an LLM directly. It goes through `LLMBackend`,
which keeps the loop testable: tests inject `FakeLLMBackend` and drive the full
pipeline with zero network access and no API key.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from .models import EngineeringError

# Stages that emit large multi-file payloads need a bigger token budget than
# the default 4096. Falling back to the default on the implement/refine stage
# is what produced "LLM returned empty response" for big projects.
_LARGE_STAGE_BUDGET = {
    "implement": 16384,
    "refine": 16384,
    "design": 8192,
}
_LLM_EMPTY_RETRIES = 3
_LLM_RETRY_BACKOFF = 2.0


@runtime_checkable
class LLMBackend(Protocol):
    """Minimal chat interface the loop depends on."""

    def complete(
        self,
        system: str,
        user: str,
        *,
        expect_json: bool = False,
        temperature: float = 0.7,
        stage: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Return assistant text for the given system/user prompt.

        Args:
            system: System prompt / instructions.
            user: The user turn (typically the task or stage-specific input).
            expect_json: Hint that the response should be JSON (advisory only).
            temperature: Sampling temperature.
            stage: Optional stage label, used by fake backends to route scripted
                responses and ignored by real backends.
            max_tokens: Optional token budget; if omitted the backend picks a
                sensible default (larger for heavy stages like implement/refine).
        """
        ...


class NallyLLMBackend:
    """Real backend that delegates to Nally's existing LLM client.

    Imports are lazy so importing this module never requires network access,
    an API key, or the `openai` package at test time.
    """

    def __init__(self, model: Optional[str] = None):
        self._model = model
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from ..agent.llm import llm as _llm
        except Exception as exc:  # pragma: no cover - import guard
            raise EngineeringError(
                "Nally LLM client unavailable: " + str(exc)
            ) from exc
        # Touching llm triggers client construction which raises a clear error
        # when no API key is configured. Surface it as an EngineeringError.
        try:
            _llm._ensure_client()
        except Exception as exc:
            raise EngineeringError(
                "LLM backend not configured (no API key?). " + str(exc)
            ) from exc
        self._client = _llm
        return self._client

    def complete(
        self,
        system: str,
        user: str,
        *,
        expect_json: bool = False,
        temperature: float = 0.7,
        stage: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        client = self._ensure_client()

        budget = max_tokens
        if budget is None:
            budget = _LARGE_STAGE_BUDGET.get(stage, 4096)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        last_err: Optional[EngineeringError] = None
        for attempt in range(1, _LLM_EMPTY_RETRIES + 1):
            try:
                response = client.chat(messages, temperature=temperature, max_tokens=budget)
                text = response.choices[0].message.content
            except Exception as exc:
                last_err = EngineeringError("LLM call failed: " + str(exc))
                if attempt < _LLM_EMPTY_RETRIES:
                    time.sleep(min(_LLM_RETRY_BACKOFF * attempt, 8))
                    continue
                raise last_err
            if text:
                return text
            last_err = EngineeringError("LLM returned empty response")
            if attempt < _LLM_EMPTY_RETRIES:
                time.sleep(min(_LLM_RETRY_BACKOFF * attempt, 8))
                continue
        raise last_err


class FakeLLMBackend:
    """Deterministic backend for tests.

    `responses` maps a stage label to either a single string or a list of
    strings. When a list is given, each call to that stage consumes the next
    entry (falling back to the last entry once exhausted). This makes it
    possible to script an initial implementation that fails tests and then a
    fixed implementation on the refine stage.
    """

    def __init__(
        self,
        responses: Optional[Dict[str, Any]] = None,
        default: str = "",
    ):
        self._responses: Dict[str, List[str]] = {}
        if responses:
            for key, val in responses.items():
                self._responses[key] = list(val) if isinstance(val, list) else [val]
        self._default = default
        self.calls: List[Dict[str, Any]] = []

    def complete(
        self,
        system: str,
        user: str,
        *,
        expect_json: bool = False,
        temperature: float = 0.7,
        stage: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        self.calls.append(
            {
                "stage": stage,
                "system": system,
                "user": user,
                "expect_json": expect_json,
            }
        )
        key = stage or "default"
        queue = self._responses.get(key)
        if not queue:
            return self._default
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]
