"""Nally Agent Graph - LangGraph-based agent loop

State machine using LangGraph. ReAct pattern:
Think -> Use Tool -> Observe -> Think -> ... -> Finish
"""

import difflib
import json
import re
import threading
import time
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from ..config import (
    ACTIVE_MODEL,
    APPROVAL_TIMEOUT,
    CONTEXT_MAX_TOKENS,
    DATA_DIR,
    DATABASE_URL,
    DUPLICATE_TOOL_THRESHOLD,
    MAX_AGENT_WALL_TIME,
    MAX_TOOL_CALLS,
    PLAN_ENABLED,
    RECURSION_LIMIT,
    SESSION_ID,
    TOKEN_WARN_THRESHOLD,
    TOOL_RETRY_LIMIT,
    ensure_data_dir,
)
from ..core.errors import LLMError
from ..core.tracing import tracer
from ..tools.permissions import gate as permission_gate
from ..tools.registry import registry
from ..utils.logger import logger


def _compute_file_diff(tool_args: dict) -> Optional[str]:
    """Compute a unified diff for file_ops write operations.

    Reads the current file (if it exists) and diffs it against the proposed content.
    Returns None if not applicable (not a write, file not readable, etc.).
    """
    try:
        if tool_args.get("action") != "write":
            return None
        file_path = tool_args.get("file_path", "")
        new_content = tool_args.get("content", "")
        if not file_path or new_content is None:
            return None

        path = Path(file_path)
        if path.exists() and path.is_file():
            old_content = path.read_text(encoding="utf-8")
        else:
            old_content = ""  # new file

        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                lineterm="",
            )
        )

        if not diff:
            return None

        # Cap at 100 lines to avoid massive payloads
        if len(diff) > 100:
            diff = diff[:100] + [f"\n... ({len(diff) - 100} more lines)"]

        return "".join(diff)
    except Exception:
        return None


SKIP_DIRS = {"__pycache__", ".git", "node_modules", "data", "logs", ".pytest_cache", "tmp"}


def _should_skip(p: Path) -> bool:
    """Check if a path is inside a skipped directory."""
    for part in p.parts:
        if part in SKIP_DIRS:
            return True
    return False


def _snapshot_project_files() -> dict:
    """Snapshot mtimes + content of tracked files in the project. Returns {path: (mtime, content)}."""
    from ..config import BASE_DIR

    snap = {}
    try:
        for p in BASE_DIR.rglob("*"):
            if p.is_file() and not _should_skip(p.relative_to(BASE_DIR)):
                try:
                    snap[str(p)] = (p.stat().st_mtime, p.read_text(encoding="utf-8"))
                except (PermissionError, OSError, UnicodeDecodeError):
                    pass
    except Exception as e:
        logger.warning(f"Failed to snapshot project files: {e}")
    return snap


def _diff_snapshots(before: dict) -> list:
    """Compare current files against before snapshot. Returns list of (filepath, diff_text)."""
    from ..config import BASE_DIR

    results = []
    try:
        for p in BASE_DIR.rglob("*"):
            if p.is_file() and not _should_skip(p.relative_to(BASE_DIR)):
                fp = str(p)
                try:
                    old = before.get(fp)
                    new_content = p.read_text(encoding="utf-8")
                    if old is None:
                        # New file
                        diff = list(
                            difflib.unified_diff(
                                [],
                                new_content.splitlines(keepends=True),
                                fromfile=f"a/{fp}",
                                tofile=f"b/{fp}",
                                lineterm="",
                            )
                        )
                        if diff:
                            results.append((fp, "".join(diff)))
                    elif old[0] != p.stat().st_mtime:
                        # Modified file
                        diff = list(
                            difflib.unified_diff(
                                old[1].splitlines(keepends=True),
                                new_content.splitlines(keepends=True),
                                fromfile=f"a/{fp}",
                                tofile=f"b/{fp}",
                                lineterm="",
                            )
                        )
                        if diff:
                            results.append((fp, "".join(diff)))
                except (PermissionError, OSError, UnicodeDecodeError):
                    pass
    except Exception as e:
        logger.warning(f"Failed to diff project snapshots: {e}")
    # Cap each diff at 100 lines
    capped = []
    for fp, d in results:
        lines = d.splitlines(keepends=True)
        if len(lines) > 100:
            d = "".join(lines[:100]) + f"\n... ({len(lines) - 100} more lines)"
        capped.append((fp, d))
    return capped


def _parse_text_tool_calls(text: str) -> tuple:
    """Parse XML-style tool calls from models that don't support native function calling."""
    pattern = r"<tool_call>\s*(\{.*?\})\s*</tool_call>"
    matches = re.findall(pattern, text, re.DOTALL)
    if not matches:
        return text, []
    tool_calls = []
    for match in matches:
        try:
            parsed = json.loads(match)
            name = parsed.get("name", "")
            args = parsed.get("args", {})
            if name:
                tool_calls.append(
                    {
                        "id": f"tc_{name}_{len(tool_calls)}",
                        "name": name,
                        "args": args if isinstance(args, dict) else {},
                    }
                )
        except json.JSONDecodeError:
            continue
    cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL).strip()
    return cleaned, tool_calls


# ── Circuit breaker settings ──────────────────────────────
MAX_CONSECUTIVE_ERRORS = 5
_MAX_RETRIES = 3
_RETRYABLE_CODES = {"500", "502", "503", "429"}

# ── Tool retry / idempotency ──────────────────────────────
# Tools whose side effects are NOT safe to repeat get no automatic retry.
# Retries only fire on transient-looking failures (timeouts, 5xx, rate limits),
# so a definitive "file not found" / "permission denied" returns immediately.
_NON_RETRYABLE_TOOLS = {"run_command", "run_code"}
_RETRYABLE_ERROR_HINTS = (
    "timeout", "timed out", "429", "503", "502", "500",
    "temporarily", "connection reset", "try again", "rate limit",
    "overloaded", "socket", "econn", "temporary failure", "gateway",
)


def _tool_is_destructive(tool_name: str, tool_args: dict) -> bool:
    if tool_name in _NON_RETRYABLE_TOOLS:
        return True
    if tool_name == "file_ops" and tool_args.get("action") in ("delete", "move", "copy"):
        return True
    return False


def _is_transient_error(result: str) -> bool:
    r = (result or "").lower()
    return any(hint in r for hint in _RETRYABLE_ERROR_HINTS)


def _execute_tool_with_retry(tool_name: str, tool_args: dict, tool_id: str) -> tuple:
    """Execute a tool, retrying transient failures up to TOOL_RETRY_LIMIT.

    Destructive tools are never retried (a failed shell command should not be
    re-run blindly). After the limit is exhausted the exact last error is
    returned so the agent can report it to the user verbatim.
    """
    if _tool_is_destructive(tool_name, tool_args):
        return registry.execute(tool_name, tool_args)

    last_result, last_success = "", False
    for attempt in range(1, TOOL_RETRY_LIMIT + 1):
        result, success = registry.execute(tool_name, tool_args)
        last_result, last_success = result, success
        if success or not _is_transient_error(result):
            return result, success
        logger.warning(
            f"Tool '{tool_name}' transient failure (attempt {attempt}/{TOOL_RETRY_LIMIT}), retrying: {result[:80]}"
        )
        if attempt < TOOL_RETRY_LIMIT:
            time.sleep(min(2 ** attempt, 8))

    if not last_success:
        logger.error(f"Tool '{tool_name}' failed after {TOOL_RETRY_LIMIT} attempts: {last_result[:200]}")
    return last_result, last_success


# ── Thread-local state ────────────────────────────────────
_tlocal = threading.local()


def _get_emit():
    return getattr(_tlocal, "emit", None)


def _set_emit(emit):
    _tlocal.emit = emit


def _ensure_tracer_store():
    """Bind the memory store to the tracer once. Best-effort; never raises."""
    try:
        if tracer._store is None:
            from ..memory import memory_store

            tracer.set_store(memory_store)
    except Exception:
        pass


# ── Approval gate ─────────────────────────────────────────
_approval_events: Dict[str, threading.Event] = {}
_approval_results: Dict[str, bool] = {}
# Approvals that arrived before the gate registered its event. Maps tc_id ->
# (approved, timestamp). Prevents the "approval lost in the race between DB
# write and event registration" bug (audit Broken #4).
_early_approvals: Dict[str, tuple] = {}
_approval_lock = threading.Lock()

# Stale early-approval entries are pruned after APPROVAL_TIMEOUT + 60s.
_APPROVAL_TTL_SLACK = 60


def _prune_early_approvals(now: float = None):
    """Remove expired entries from _early_approvals. Caller must hold _approval_lock."""
    if now is None:
        now = time.time()
    ttl = (APPROVAL_TIMEOUT or 1800) + _APPROVAL_TTL_SLACK
    stale = [k for k, (_, ts) in _early_approvals.items() if now - ts > ttl]
    for k in stale:
        _early_approvals.pop(k, None)


def _pop_approval_state(tc_id: str) -> tuple:
    """Thread-safe: pop both event and result for a tc_id. Returns (event, result)."""
    with _approval_lock:
        event = _approval_events.pop(tc_id, None)
        result = _approval_results.pop(tc_id, False)
        return event, result


def _get_approval_db():
    import sqlite3
    db_path = DATA_DIR / "nally.db"
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_approvals (
            tool_call_id TEXT PRIMARY KEY,
            status TEXT,
            created_at REAL,
            updated_at REAL
        )
    """)
    return conn


def _save_pending_approval(tool_call_id: str, status: str = "pending"):
    try:
        conn = _get_approval_db()
        now = time.time()
        conn.execute("""
            INSERT OR REPLACE INTO pending_approvals (tool_call_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        """, (tool_call_id, status, now, now))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"Failed to save pending approval: {e}")


def _get_approval_status(tool_call_id: str) -> Optional[str]:
    try:
        conn = _get_approval_db()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM pending_approvals WHERE tool_call_id = ?", (tool_call_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.debug(f"Failed to get approval status: {e}")
        return None


# ── Abort checkpoint ──────────────────────────────────────
def _check_abort(thread_id: str) -> bool:
    """Check if user requested abort for this session."""
    from ..core.abort import check_abort

    return check_abort(thread_id)


def _clear_abort(thread_id: str):
    """Clear abort flag for this session."""
    from ..core.abort import clear_abort

    clear_abort(thread_id)


def _has_duplicate_tool_calls(messages: list, window: int = 6) -> bool:
    """Detect doom loops — same tool with same args called repeatedly."""
    recent = messages[-window:]
    seen = {}
    for msg in recent:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                key = f"{tc['name']}:{json.dumps(tc['args'], sort_keys=True)}"
                seen[key] = seen.get(key, 0) + 1
                if seen[key] >= DUPLICATE_TOOL_THRESHOLD:
                    return True
    return False


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    tools: List[Dict[str, Any]]
    iteration: int
    max_iterations: int
    error_count: int
    last_error: Optional[str]
    tool_calls_total: int
    thread_id: str
    plan: Optional[Any]
    plan_status: str
    step_results: Dict[str, str]
    current_step_index: int
    model_override: Optional[str]
    start_time: float


def _convert_to_openai(messages: List[BaseMessage]) -> List[dict]:
    """Convert LangChain messages to OpenAI format."""
    openai_messages = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            openai_messages.append({"role": "system", "content": msg.content})
        elif isinstance(msg, HumanMessage):
            openai_messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            msg_dict: dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"]) if isinstance(tc["args"], dict) else tc["args"],
                        },
                    }
                    for tc in msg.tool_calls
                ]
            openai_messages.append(msg_dict)
        elif isinstance(msg, ToolMessage):
            openai_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                }
            )
    return openai_messages


def _safe_parse_tool_args(arguments: str) -> dict:
    """Parse tool call arguments JSON, returning empty dict on malformed input."""
    if not arguments:
        return {}
    try:
        return json.loads(arguments)
    except (json.JSONDecodeError, ValueError):
        logger.warning(f"Malformed tool call arguments (len={len(arguments)}), using empty args: {arguments[:80]!r}...")
        return {}


def _stream_with_emit(llm_client, openai_messages, tools, cache_key, emit):
    """Stream LLM response and emit chunks. Returns ChatCompletion-like object."""
    from openai.types.chat import ChatCompletion, ChatCompletionMessage
    from openai.types.chat.chat_completion import Choice

    collected_content = []
    collected_tool_calls = []

    for event in llm_client.stream_chat_with_tools(
        openai_messages, tools=tools if tools else None, cache_key=cache_key
    ):
        if event["type"] == "content":
            collected_content.append(event["text"])
            try:
                emit("stream_chunk", {"text": event["text"]})
            except Exception:
                pass
        elif event["type"] == "tool_call":
            collected_tool_calls.append(event)

    try:
        emit("stream_done", {})
    except Exception:
        pass

    full_content = "".join(collected_content)

    if not collected_tool_calls and full_content:
        full_content, text_tool_calls = _parse_text_tool_calls(full_content)
        collected_tool_calls.extend(text_tool_calls)

    if collected_tool_calls:
        tc_list = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc["args"]) if isinstance(tc["args"], dict) else json.dumps({}),
                },
            }
            for tc in collected_tool_calls
        ]
        assistant_msg = ChatCompletionMessage(role="assistant", content=full_content or "", tool_calls=tc_list)
    else:
        assistant_msg = ChatCompletionMessage(role="assistant", content=full_content)

    return ChatCompletion(
        id="stream",
        choices=[Choice(finish_reason="stop", index=0, message=assistant_msg)],
        created=0,
        model="",
        object="chat.completion",
    )


_RATE_LIMIT_RETRIES = 6  # more retries for rate limits (needs longer waits)
_RATE_LIMIT_BASE_WAIT = 30  # seconds — free tier limits typically reset in ~60s


def _call_llm_with_retry(llm_client, openai_messages, tools, cache_key, emit, model=None):
    """Call LLM with streaming + retry. Raises LLMError on failure.

    On 429 rate limit, rotates to the next API key. After all keys are
    exhausted, waits longer for the rate limit window to reset before
    cycling through keys again.

    Args:
        model: Optional model override (bypasses routing, used by sub-agents).
            When set, streaming is skipped (chat_with_model doesn't support it)
            but retries still apply on transient errors.
    """
    max_retries = _RATE_LIMIT_RETRIES if not model else _MAX_RETRIES
    last_error = None
    keys_exhausted_count = 0

    for attempt in range(max_retries):
        try:
            if emit and not model:
                try:
                    return _stream_with_emit(llm_client, openai_messages, tools, cache_key, emit)
                except Exception as stream_err:
                    logger.warning(f"Streaming failed, falling back: {stream_err}")
                    try:
                        emit("stream_done", {})
                    except Exception:
                        pass
            if model:
                response = llm_client.chat_with_model(model, openai_messages, tools, cache_key=cache_key)
            else:
                response = llm_client.chat(openai_messages, tools=tools if tools else None, cache_key=cache_key)
            return response

        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            is_retryable = any(code in error_str for code in _RETRYABLE_CODES)
            is_rate_limit = "429" in error_str or "rate" in error_str

            if attempt < max_retries - 1 and is_retryable:
                if is_rate_limit:
                    rotated = llm_client.rotate_key()
                    if rotated:
                        # Key rotated — short wait, try new key fast
                        wait = 2
                    else:
                        # All keys exhausted — wait longer for rate limit reset
                        keys_exhausted_count += 1
                        wait = min(_RATE_LIMIT_BASE_WAIT * keys_exhausted_count, 120)
                        logger.warning(
                            f"All {len(llm_client._keys)} keys rate limited, "
                            f"waiting {wait}s for limit reset (cycle {keys_exhausted_count})"
                        )
                else:
                    wait = min(2 ** (attempt + 1), 15)

                logger.warning(
                    f"LLM call failed (attempt {attempt + 1}/{max_retries}), retrying in {wait}s: {str(e)[:80]}"
                )
                time.sleep(wait)
            else:
                break

    if last_error:
        error_str = str(last_error).lower()
        if "429" in error_str or "rate" in error_str:
            raise LLMError.rate_limit(provider="llm")
        elif "overloaded" in error_str or "503" in error_str:
            raise LLMError.overloaded(provider="llm")
        elif "auth" in error_str or "401" in error_str:
            raise LLMError.auth_failed(provider="llm")
        else:
            raise LLMError.connection_failed(provider="llm", reason=str(last_error)[:200])


def llm_call(state: AgentState) -> AgentState:
    """Call the LLM with current messages and tools."""
    from .llm import llm

    messages = state["messages"]
    tools = state["tools"]
    iteration = state.get("iteration", 0)
    error_count = state.get("error_count", 0)
    tool_calls_total = state.get("tool_calls_total", 0)
    thread_id = state.get("thread_id", "default")
    cache_key = thread_id

    # Abort checkpoint — stop immediately if user requested abort
    if _check_abort(thread_id):
        _clear_abort(thread_id)
        return {"messages": [AIMessage(content="Operation aborted by user.")], "iteration": iteration + 1}

    if error_count >= MAX_CONSECUTIVE_ERRORS:
        logger.warning(f"Circuit breaker: {error_count} consecutive errors, stopping agent")
        fallback = AIMessage(
            content=(
                f"Execution halted: hit {error_count} consecutive errors. "
                f"Here is the partial data I gathered before stopping "
                f"({tool_calls_total} tool calls made). Please try again or rephrase your request."
            )
        )
        return {"messages": [fallback], "iteration": iteration + 1, "error_count": 0}

    if tool_calls_total >= MAX_TOOL_CALLS:
        logger.warning(f"Circuit breaker: {tool_calls_total} total tool calls, stopping agent")
        # Make one final LLM call to summarize findings — no tools, no recursion
        try:
            summary_msgs = _convert_to_openai(messages) + [
                {
                    "role": "system",
                    "content": (
                        "You have reached the maximum number of tool calls. "
                        "Do NOT call any more tools. Instead, summarize everything you have found so far "
                        "based on the conversation history and tool results. Be thorough and specific — "
                        "reference actual findings, not generic placeholders."
                    ),
                }
            ]
            response = llm.chat(summary_msgs, tools=None, cache_key=cache_key)
            summary = (
                response.choices[0].message.content
                or "I've reached the tool call limit. Here's what I found so far."
            )
        except Exception as e:
            logger.warning(f"Circuit breaker summary call failed: {e}")
            summary = "I've reached the maximum number of tool calls. Please try again or rephrase your request."
        fallback = AIMessage(
            content=f"Execution halted: reached the maximum of {MAX_TOOL_CALLS} tool calls. "
            f"Here is the partial data I gathered before stopping:\n\n{summary}"
        )
        return {"messages": [fallback], "iteration": iteration + 1}

    emit = _get_emit()
    if emit and messages:
        last_msg = messages[-1]
        if hasattr(last_msg, "content") and last_msg.content:
            try:
                emit("thought", {"text": last_msg.content[:500]})
            except Exception:
                pass

    openai_messages = _convert_to_openai(messages)

    # ── Token budget early-warning ──────────────────────────
    # Proactively warn (and instruct concision) before we blow the context
    # window — this is what prevents the silent token-exhaustion crash.
    try:
        from ..agent.context import context_manager

        est_tokens = context_manager.estimate_tokens(openai_messages)
        if est_tokens >= TOKEN_WARN_THRESHOLD * CONTEXT_MAX_TOKENS:
            logger.warning(
                f"Token budget warning: ~{est_tokens} tokens (>= {int(TOKEN_WARN_THRESHOLD * 100)}% of {CONTEXT_MAX_TOKENS})"
            )
            emit = _get_emit()
            if emit:
                try:
                    emit(
                        "system_notice",
                        {
                            "text": (
                                "I'm approaching my token limit. I'll save key findings to memory and "
                                "summarize before we continue — say 'continue' when you want me to pick back up."
                            )
                        },
                    )
                except Exception:
                    pass
            openai_messages.append(
                {
                    "role": "system",
                    "content": (
                        "TOKEN WARNING: context is near the limit. Be concise. If the remaining work is "
                        "large, persist findings to memory now and give a compact summary instead of "
                        "continuing at length."
                    ),
                }
            )
    except Exception as e:
        logger.debug(f"Token budget check skipped: {e}")

    # Inject recent tool execution receipts (trust grounding)
    try:
        from ..tools.receipts import receipt_store

        recent_receipts = receipt_store.get_recent(limit=20)
        if recent_receipts:
            receipt_summary = receipt_store.format_for_context(recent_receipts)
            openai_messages.append({"role": "system", "content": receipt_summary})
    except Exception as e:
        logger.warning(f"Failed to inject receipts into context: {e}")

    model_override = state.get("model_override")

    llm_span = tracer.start_span("llm_call", {
        "model": model_override or ACTIVE_MODEL,
        "messages_count": len(openai_messages),
        "tools_count": len(tools) if tools else 0,
    })

    try:
        response = _call_llm_with_retry(llm, openai_messages, tools, cache_key, emit, model=model_override)
    except LLMError as e:
        tracer.end_span(llm_span.span_id, error=e.message)
        new_error_count = error_count + 1
        logger.error(f"LLM error ({new_error_count}/{MAX_CONSECUTIVE_ERRORS}): {e.message}")
        fallback = AIMessage(content=e.to_llm_format())
        return {
            "messages": [fallback],
            "iteration": iteration + 1,
            "error_count": new_error_count,
            "last_error": e.message[:200],
        }

    assistant_msg = response.choices[0].message

    # End llm_span on success
    tracer.end_span(llm_span.span_id, output={
        "content_preview": (assistant_msg.content or "")[:300],
        "tool_calls": [{"name": tc.function.name} for tc in (assistant_msg.tool_calls or [])],
    })

    if not assistant_msg.tool_calls and assistant_msg.content:
        cleaned_text, text_tool_calls = _parse_text_tool_calls(assistant_msg.content)
        if text_tool_calls:
            assistant_msg.content = cleaned_text
            from openai.types.chat.chat_completion_message import ChatCompletionMessageToolCall
            from openai.types.chat.chat_completion_message_function import Function

            assistant_msg.tool_calls = [
                ChatCompletionMessageToolCall(
                    id=tc["id"],
                    type="function",
                    function=Function(name=tc["name"], arguments=json.dumps(tc["args"])),
                )
                for tc in text_tool_calls
            ]

    ai_message = AIMessage(
        content=assistant_msg.content or "",
        tool_calls=[
            {
                "id": tc.id,
                "name": tc.function.name,
                "args": _safe_parse_tool_args(tc.function.arguments),
            }
            for tc in (assistant_msg.tool_calls or [])
        ]
        if assistant_msg.tool_calls
        else [],
    )

    # Post-response verification — check claims against receipts
    if ai_message.content and not ai_message.tool_calls:
        try:
            from ..tools.receipts import receipt_store
            from ..tools.registry import registry
            from .verifier import claim_verifier

            recent = receipt_store.get_recent(limit=20)
            registered_tools = set(registry.tools.keys())
            if recent:
                vresult = claim_verifier.verify(ai_message.content, recent, registered_tools)
                if not vresult.is_honest:
                    logger.warning(
                        f"Claim verification: {vresult.unsupported_count} unsupported, "
                        f"{vresult.contradicted_count} contradicted"
                    )
                    # Feed verification failure back to LLM for self-correction
                    correction_prompt = (
                        "VERIFICATION FAILED — your last response contained unsupported claims:\n"
                    )
                    for f in vresult.findings:
                        if f.verdict.value in ("unsupported", "contradicted"):
                            correction_prompt += f"- [{f.verdict.value}] {f.claim}: {f.evidence}\n"
                    correction_prompt += (
                        "\nRewrite your response. Remove or correct any claims not backed by receipts. "
                        "If you did not call a tool, do not claim you did. "
                        "If a tool failed, say it failed. Do not invent numbers or limits."
                    )
                    try:
                        from .llm import call_llm
                        corrected = call_llm(
                            messages=[
                                {"role": "system", "content": "You are Nally. Fix your previous response based on the verification feedback. Output ONLY the corrected response, no preamble."},
                                {"role": "user", "content": correction_prompt},
                            ],
                            temperature=0.1,
                        )
                        if corrected and not corrected.startswith("Error"):
                            ai_message.content = corrected
                            logger.info("LLM self-corrected after verification failure")
                    except Exception as correction_err:
                        logger.warning(f"Self-correction call failed: {correction_err}")
                    if emit:
                        try:
                            emit("verification", vresult.to_dict())
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"Claim verification failed: {e}")

    if emit and assistant_msg.tool_calls:
        for tc in assistant_msg.tool_calls:
            try:
                emit(
                    "tool_call",
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "args": json.loads(tc.function.arguments) if tc.function.arguments else {},
                        "iteration": iteration + 1,
                    },
                )
            except Exception:
                pass

    return {
        "messages": [ai_message],
        "iteration": iteration + 1,
        "error_count": 0,
        "last_error": None,
    }


def tool_executor(state: AgentState) -> AgentState:
    """Execute tool calls from the last AI message (parallel via ThreadPoolExecutor)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    messages = state["messages"]
    emit = _get_emit()
    tool_calls_total = state.get("tool_calls_total", 0)
    thread_id = state.get("thread_id", "default")

    if emit is None:
        logger.warning("tool_executor: emit is None — approval buttons won't work")

    # Abort checkpoint — stop immediately if user requested abort
    if _check_abort(thread_id):
        _clear_abort(thread_id)
        return {"messages": [AIMessage(content="Operation aborted by user.")], "tool_calls_total": tool_calls_total}

    last_ai_msg = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            last_ai_msg = msg
            break

    if not last_ai_msg:
        return {"messages": [], "tool_calls_total": tool_calls_total}

    # Capture current tracing context BEFORE dispatching to pool threads
    # (thread-local span stack does not propagate into ThreadPoolExecutor).
    _trace_parent = tracer.get_current_span()
    _trace_parent_id = _trace_parent.span_id if _trace_parent else None
    _trace_run_id = _trace_parent.run_id if _trace_parent else None

    def _execute_single(tc):
        tool_name = tc["name"]
        tool_args = tc["args"]
        tool_id = tc["id"]

        # ── Idempotency (task_id) ───────────────────────────
        # If the model supplied a task_id, skip re-execution when that task was
        # already completed in this session. Makes tools safe to retry/duplicate.
        task_id = tool_args.get("task_id") if isinstance(tool_args, dict) else None
        if task_id:
            try:
                from ..tools.receipts import receipt_store

                cached = receipt_store.get_idempotent(str(task_id), SESSION_ID)
                if cached is not None:
                    logger.info(f"Idempotent skip: task_id={task_id} already processed — returning cached result")
                    _finish(True, "idempotent skip")
                    return ToolMessage(content=cached, tool_call_id=tool_id)
            except Exception as e:
                logger.debug(f"Idempotency check skipped: {e}")

        tool_span = None
        try:
            tool_span = tracer.start_span(
                f"tool:{tool_name}",
                {"name": tool_name, "args": tool_args, "tool_call_id": tool_id},
                parent_span_id=_trace_parent_id,
                run_id=_trace_run_id,
            )
        except Exception:
            tool_span = None

        def _finish(success_flag, result_str, error_str=None):
            if tool_span is not None:
                try:
                    tracer.end_span(
                        tool_span.span_id,
                        output={"success": success_flag, "result": result_str},
                        error=error_str,
                    )
                except Exception:
                    pass

        decision = permission_gate.check(tool_name, tool_args)

        if decision.value == "deny":
            logger.info(f"Permission denied: '{tool_name}' {tool_args}")
            _finish(False, "denied by permission config")
            return ToolMessage(
                content=f"Blocked: '{tool_name}' is denied by permission config.",
                tool_call_id=tool_id,
            )

        if decision.value == "ask":
            existing_status = _get_approval_status(tool_id)
            if existing_status == "approved":
                logger.info(f"Approval gate: '{tool_name}' pre-approved via DB")
                approved = True
                result_approved = True
            elif existing_status == "denied":
                logger.info(f"Approval gate: '{tool_name}' pre-denied via DB")
                approved = False
                result_approved = False
            else:
                # Register the in-memory event BEFORE persisting pending so a
                # fast approval (web/ws/telegram) can never arrive before the
                # gate is registered — the approval-race fix (audit Broken #4).
                approval_event = threading.Event()
                with _approval_lock:
                    _approval_events[tool_id] = approval_event
                    _approval_results[tool_id] = False
                    _prune_early_approvals()
                    early = _early_approvals.pop(tool_id, None)
                    if early is not None:
                        _approval_results[tool_id] = early[0]
                        approval_event.set()
                        logger.info(
                            f"approval_gate: early resolution '{early[0]}' applied for tc_id={tool_id}"
                        )
                _save_pending_approval(tool_id, "pending")

                # Compute diff preview for file write operations
                diff = _compute_file_diff(tool_args)

                if emit:
                    try:
                        payload = {
                            "tool_call_id": tool_id,
                            "name": tool_name,
                            "args": tool_args,
                            "permission": "ask",
                        }
                        if diff:
                            payload["diff"] = diff
                            payload["file_path"] = tool_args.get("file_path", "")
                        logger.info(f"approval_gate: emitting confirmation_required for '{tool_name}' tc_id={tool_id}")
                        emit("confirmation_required", payload)
                        logger.info(f"approval_gate: emit sent successfully for tc_id={tool_id}")
                    except Exception as e:
                        logger.error(f"approval_gate: emit failed for tc_id={tool_id}: {e}")
                else:
                    logger.warning(f"approval_gate: emit is None for '{tool_name}' — approval buttons won't appear")

                logger.info(f"Approval gate: waiting for user confirmation of '{tool_name}' (timeout: {APPROVAL_TIMEOUT}s)")

                # Wait on the event instead of sleep-polling: Event.wait(timeout)
                # wakes immediately when resolve_approval sets the event and
                # burns no CPU while waiting (audit Architecture Risk #1). Abort
                # is still checked each iteration so a user abort breaks the
                # wait immediately.
                _poll_interval = 2
                _polls = (APPROVAL_TIMEOUT or 1800) // _poll_interval
                for _i in range(_polls):
                    if approval_event.is_set():
                        break
                    if _check_abort(thread_id):
                        _pop_approval_state(tool_id)
                        _save_pending_approval(tool_id, "aborted")
                        _finish(False, "aborted by user")
                        return ToolMessage(content="Aborted by user.", tool_call_id=tool_id)
                    approval_event.wait(_poll_interval)

                approved = approval_event.is_set()
                _, result_approved = _pop_approval_state(tool_id)

                if not result_approved:
                    result_approved = (_get_approval_status(tool_id) == "approved")

            if not approved or not result_approved:
                _save_pending_approval(tool_id, "denied")
                logger.info(f"Approval gate: user denied or timed out for '{tool_name}'")
                _finish(False, "declined or timed out")
                return ToolMessage(
                    content=f"Action '{tool_name}' was declined or timed out.",
                    tool_call_id=tool_id,
                )

            _save_pending_approval(tool_id, "approved")

            logger.info(f"Approval gate: user approved '{tool_name}'")

        # Compute diff BEFORE execution (old content still on disk)
        diff = None
        file_path_str = ""
        snapshot_before = None
        if tool_name == "file_ops" and tool_args.get("action") == "write":
            diff = _compute_file_diff(tool_args)
            file_path_str = tool_args.get("file_path", "")
            logger.info(f"Diff computed for {file_path_str}: {'yes' if diff else 'empty/same'}")
        elif tool_name == "run_command":
            snapshot_before = _snapshot_project_files()

        start = time.time()
        try:
            result, success = _execute_tool_with_retry(tool_name, tool_args, tool_id)
        except Exception as e:
            result = f"Error executing {tool_name}: {e!s}"
            success = False
            logger.error_with_context(f"Tool {tool_name} failed", e)

        duration = (time.time() - start) * 1000
        logger.tool_call(tool_name, tool_args, result)

        # Persist idempotency result so the same task_id is never re-run.
        if success and task_id:
            try:
                from ..tools.receipts import receipt_store

                receipt_store.record_idempotent(str(task_id), SESSION_ID, str(result))
            except Exception as e:
                logger.debug(f"Idempotency record skipped: {e}")

        # Generate execution receipt (trust system)
        try:
            from ..tools.receipts import receipt_store

            receipt_store.record(
                tool_call_id=tool_id,
                tool=tool_name,
                args=tool_args,
                result=str(result)[:2000],
                success=success,
                duration_ms=duration,
            )
        except Exception as e:
            logger.warning(f"Failed to record receipt for {tool_name}: {e}")

        # For run_command, detect changed files via snapshot diff
        if snapshot_before is not None and success:
            changes = _diff_snapshots(snapshot_before)
            if changes:
                diff = "".join(d for _, d in changes)
                file_path_str = ", ".join(Path(fp).name for fp, _ in changes[:3])
                if len(changes) > 3:
                    file_path_str += f" +{len(changes) - 3} more"
                logger.info(f"Snapshot diff: {len(changes)} files changed")

        if emit:
            try:
                result_str = str(result)
                if len(result_str) > 500:
                    if "IMAGE_FILE:" in result_str:
                        result_str = "..." + result_str[-497:]
                    else:
                        result_str = result_str[:500]
                payload = {
                    "tool_call_id": tool_id,
                    "name": tool_name,
                    "result": result_str,
                    "duration_ms": round(duration),
                    "success": success,
                }
                if diff:
                    payload["diff"] = diff
                    payload["file_path"] = file_path_str
                emit("tool_result", payload)
            except Exception:
                pass

        _finish(success, str(result)[:2000])
        return ToolMessage(content=str(result)[:2000], tool_call_id=tool_id)

    tool_messages = []
    waits = []

    # Capture current tracing context BEFORE dispatching to pool threads
    # (thread-local span stack does not propagate into ThreadPoolExecutor).
    _trace_parent = tracer.get_current_span()
    _trace_parent_id = _trace_parent.span_id if _trace_parent else None
    _trace_run_id = _trace_parent.run_id if _trace_parent else None

    # Capture the current context (incl. SUBAGENT_DEPTH) so worker threads see
    # the same nesting depth — required for correct sub-agent depth limiting.
    import contextvars

    ctx = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=min(len(last_ai_msg.tool_calls), 5)) as executor:
        futures = {executor.submit(ctx.run, _execute_single, tc): tc for tc in last_ai_msg.tool_calls}
        for future in as_completed(futures):
            try:
                tool_messages.append(future.result())
            except Exception as e:
                tc = futures[future]
                tool_messages.append(ToolMessage(content=f"Error: {e!s}", tool_call_id=tc["id"]))

    return {
        "messages": tool_messages,
        "tool_calls_total": tool_calls_total + len(last_ai_msg.tool_calls),
    }


def should_continue(state: AgentState) -> str:
    """Determine if we should continue the agent loop."""
    messages = state["messages"]
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 10)
    thread_id = state.get("thread_id", "default")

    # Trace the exit reason for every "end" path
    _current_run_id = None
    _span = tracer.get_current_span()
    if _span:
        _current_run_id = _span.run_id

    def _record_exit(reason):
        try:
            tracer.end_span(
                tracer.start_span("loop_exit", {"reason": reason}, run_id=_current_run_id).span_id,
                output={"reason": reason, "iteration": iteration},
            )
        except Exception:
            pass

    # Abort checkpoint — stop at next decision point
    if _check_abort(thread_id):
        _clear_abort(thread_id)
        _record_exit("aborted")
        return "end"

    # Wall-clock budget
    start_time = state.get("start_time", 0)
    if start_time and (time.time() - start_time) > MAX_AGENT_WALL_TIME:
        logger.warning(f"Agent exceeded {MAX_AGENT_WALL_TIME}s wall-clock budget")
        emit = _get_emit()
        if emit:
            try:
                emit("system_notice", {"text": f"Execution halted: hit my {MAX_AGENT_WALL_TIME}s time budget for this turn — say 'continue' if you want me to keep going."})
            except Exception:
                pass
        _record_exit("wall_clock")
        return "end"

    if iteration >= max_iterations:
        logger.debug(f"Agent reached max iterations ({max_iterations})")
        emit = _get_emit()
        if emit:
            try:
                emit("system_notice", {"text": "Execution halted: hit my step limit for this turn — say 'continue' to proceed."})
            except Exception:
                pass
        _record_exit("max_iterations")
        return "end"

    # Duplicate tool call detection (doom loop)
    if _has_duplicate_tool_calls(messages):
        logger.warning("Duplicate tool call detected, forcing stop")
        emit = _get_emit()
        if emit:
            try:
                emit("system_notice", {"text": "Execution halted: I noticed I was repeating the same action and stopped — let me know how you'd like to proceed."})
            except Exception:
                pass
        _record_exit("doom_loop")
        return "end"

    last_ai_msg = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            last_ai_msg = msg
            break

    if not last_ai_msg or not last_ai_msg.tool_calls:
        _record_exit("natural")
        return "end"

    return "tools"


def _create_checkpointer():
    """Create the best available checkpointer."""
    if DATABASE_URL:
        try:
            import sqlite3

            from langgraph.checkpoint.sqlite import SqliteSaver

            conn = sqlite3.connect(DATABASE_URL, check_same_thread=False)
            logger.info(f"Using database checkpointer: {DATABASE_URL}")
            return SqliteSaver(conn)
        except Exception as e:
            logger.warning(f"Database checkpointer failed: {e}, falling back")

    try:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver

        ensure_data_dir()
        from ..config import DATA_DIR

        db_path = str(DATA_DIR / "checkpoints.db")
        conn = sqlite3.connect(db_path, check_same_thread=False)
        logger.info(f"Using local SQLite checkpointer: {db_path}")
        return SqliteSaver(conn)
    except Exception as e:
        logger.warning(f"SQLite checkpointer failed: {e}, using in-memory")

    return MemorySaver()


def create_agent_graph():
    """Create the LangGraph state machine for the agent with checkpointing.

    When PLAN_ENABLED, adds planner topology:
        classify -> (planner | llm)
        planner -> execute_step -> replan -> (execute_step | planner | synthesize | llm)
        synthesize -> END
    """
    graph = StateGraph(AgentState)

    # ── ReAct nodes (always present) ──
    graph.add_node("llm", llm_call)
    graph.add_node("tools", tool_executor)

    # ── Planning nodes (optional) ──
    if PLAN_ENABLED:
        from .planner import (
            classify_node,
            execute_step_node,
            planner_node,
            replan_node,
            route_after_classify,
            route_after_replan,
            synthesize_node,
        )

        graph.add_node("classify", classify_node)
        graph.add_node("planner", planner_node)
        graph.add_node("execute_step", execute_step_node)
        graph.add_node("replan", replan_node)
        graph.add_node("synthesize", synthesize_node)

        # classify decides: planner or ReAct?
        graph.add_conditional_edges(
            "classify",
            route_after_classify,
            {"planner": "planner", "llm": "llm"},
        )

        # planner -> execute_step (always)
        graph.add_edge("planner", "execute_step")

        # execute_step -> replan (always)
        graph.add_edge("execute_step", "replan")

        # replan routes based on plan status
        graph.add_conditional_edges(
            "replan",
            route_after_replan,
            {
                "execute_step": "execute_step",
                "planner": "planner",
                "synthesize": "synthesize",
            },
        )

        # synthesize -> END
        graph.add_edge("synthesize", END)

        # Entry point is classify
        graph.set_entry_point("classify")
    else:
        # Pure ReAct (no planning) — entry point is llm
        graph.set_entry_point("llm")

    # ReAct loop edges (always present)
    graph.add_conditional_edges("llm", should_continue, {"tools": "tools", "end": END})
    graph.add_edge("tools", "llm")

    checkpointer = _create_checkpointer()
    return graph.compile(checkpointer=checkpointer)


# Lazy singleton
_agent_graph = None
_graph_lock = threading.Lock()


def _get_graph():
    global _agent_graph
    if _agent_graph is None:
        with _graph_lock:
            if _agent_graph is None:
                _agent_graph = create_agent_graph()
    return _agent_graph


def run_agent(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    emit=None,
    max_iterations: int = 10,
    thread_id: str = "default",
    model: Optional[str] = None,
    _parent_span_id: Optional[str] = None,
    _run_id: Optional[str] = None,
) -> str:
    """Run the agent graph and return the final response."""
    _ensure_tracer_store()
    entry_depth = tracer.stack_depth()
    root_span = None
    try:
        root_span = tracer.start_span(
            "agent_run",
            {
                "messages": messages,
                "tools": [t.get("function", {}).get("name") if isinstance(t, dict) else t for t in tools],
                "model": model,
                "thread_id": thread_id,
            },
            parent_span_id=_parent_span_id,
            run_id=_run_id,
        )
        # Surface the run_id to the frontend so it can link messages to traces.
        if emit and root_span is not None:
            try:
                emit("run_id", {"run_id": root_span.run_id})
            except Exception:
                pass
    except Exception:
        root_span = None
        try:
            tracer.truncate_to(entry_depth)
        except Exception:
            pass

    chain_response = None
    lc_messages = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        elif role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            tool_calls = msg.get("tool_calls", [])
            lc_messages.append(AIMessage(content=content, tool_calls=tool_calls))
        elif role == "tool":
            lc_messages.append(ToolMessage(content=content, tool_call_id=msg.get("tool_call_id", "")))

    _set_emit(emit)

    # Use a fresh thread_id per invocation to prevent checkpointer message
    # accumulation. The NallyAgent manages its own history — the checkpointer
    # must NOT merge old state with new, or messages double every call.
    import uuid

    fresh_thread = f"{thread_id}-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": fresh_thread}, "recursion_limit": RECURSION_LIMIT}

    # Bridge the transient fresh_thread back to the stable session id so abort
    # flags set via set_abort(session_id) are seen by graph checkpoints that
    # key on state["thread_id"] (audit Broken #5).
    from ..core.abort import clear_alias, register_alias

    register_alias(fresh_thread, thread_id)

    initial_state = {
        "messages": lc_messages,
        "tools": tools,
        "iteration": 0,
        "max_iterations": max_iterations,
        "error_count": 0,
        "last_error": None,
        "tool_calls_total": 0,
        "thread_id": fresh_thread,
        "plan": None,
        "plan_status": "",
        "step_results": {},
        "current_step_index": 0,
        "model_override": model,
        "start_time": time.time(),
    }

    try:
        graph = _get_graph()
        result = graph.invoke(initial_state, config=config)
        _set_emit(None)

        final_messages = result["messages"]
        for msg in reversed(final_messages):
            if isinstance(msg, AIMessage) and msg.content:
                chain_response = msg.content
                break

        chain_response = chain_response or "Done."

    except Exception as e:
        _set_emit(None)
        clear_alias(fresh_thread)
        logger.error(f"Agent graph failed: {e}")
        if root_span is not None:
            try:
                tracer.end_span_exc(root_span.span_id, e)
            except Exception:
                pass
        try:
            tracer.truncate_to(entry_depth)
        except Exception:
            pass
        raise

    if root_span is not None:
        try:
            tracer.end_span(
                root_span.span_id,
                output={"response": chain_response, "reason": "completed"},
            )
        except Exception:
            pass
    try:
        tracer.truncate_to(entry_depth)
    except Exception:
        pass
    clear_alias(fresh_thread)
    return chain_response


def resolve_approval(tool_call_id: str, approved: bool) -> bool:
    """Resolve a pending approval request from the frontend or Telegram inline button.

    Persists decision to SQLite so approvals survive server restarts. Returns True if
    the approval request was found (either in-memory or persisted in DB).
    """
    status_str = "approved" if approved else "denied"
    _save_pending_approval(tool_call_id, status_str)
    logger.info(f"resolve_approval: tc_id={tool_call_id}, approved={approved}, status saved to DB")

    # Thread-safe: check and signal
    with _approval_lock:
        _prune_early_approvals()
        event = _approval_events.get(tool_call_id)
        if event:
            _approval_results[tool_call_id] = approved
            event.set()
            logger.info(f"resolve_approval: event set for tc_id={tool_call_id}")
            return True
        # Approval arrived before the gate registered its event. Cache it so
        # the gate applies it as soon as it registers (audit Broken #4).
        _early_approvals[tool_call_id] = (approved, time.time())
        logger.info(
            f"resolve_approval: no event yet for tc_id={tool_call_id}, cached early result ({approved})"
        )
        return True
