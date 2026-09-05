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
    MAX_TOOL_FAILURES_PER_TURN,
    MAX_TOOL_CALLS,
    PLAN_ENABLED,
    RECURSION_LIMIT,
    SESSION_ID,
    TOKEN_WARN_THRESHOLD,
    TOOL_RETRY_LIMIT,
    WALL_TIME_OVERRIDES,
    ensure_data_dir,
)
from ..core.errors import LLMError
from ..core.tracing import tracer
from ..tools.permissions import gate as permission_gate
from ..tools.registry import registry
from ..utils.logger import logger

# ── Checkpoint system (Phase 1: file-state rewind, vibe-style) ──
try:
    from ..core.checkpoints.checkpointer import Checkpointer
    from ..core.checkpoints.file_store import FileStore

    checkpointer = Checkpointer(max_turns=100)
    checkpoint_store = FileStore()
except Exception as _cp_err:  # pragma: no cover - never crash agent if checkpoint fails to init
    checkpointer = None  # type: ignore
    checkpoint_store = None  # type: ignore


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
    """Parse XML-style tool calls from models that don't support native function calling.

    Handles two formats:
    1. Standard: `` — JSON payload in tags
    2. Alternate: <tool_calls:ID> wrapper with <tool_call:ID>name and
       <tool_call:IDparameter name="key">value lines (with or without
       closing <tool_call:IDend> / </tool_calls:ID> tags).

    hy3-free and similar models often omit the closing tags.
    """
    # First try standard `` format
    pattern = r"<tool_call>\s*(\{.*?\})\s*</tool_call>"
    matches = re.findall(pattern, text, re.DOTALL)

    # Parse alternate format: find each <tool_calls:ID>...</tool_calls:ID> block
    # and extract tool name + params from within it.
    tool_calls = []

    # Match wrapper blocks (with or without closing tag)
    # Group 1: the hex ID, Group 2: everything inside the wrapper
    wrapper_re = re.compile(
        r"<tool_calls:([a-f0-9]+)>"       # opening wrapper
        r"(.*?)"                            # content inside
        r"(?:</tool_calls:\1>|(?=\Z))",    # closing wrapper OR end-of-string
        re.DOTALL,
    )

    if not matches:
        for wrapper_match in wrapper_re.finditer(text):
            tc_id = wrapper_match.group(1)
            block = wrapper_match.group(2)

            # Find ALL <tool_call:ID>word occurrences in this block
            # Each one is a separate tool call (bare name, possibly with params)
            all_tool_names = re.findall(
                r"<tool_call:" + tc_id + r">(\w+)", block
            )

            for tool_name in all_tool_names:
                # Skip if this is actually a "parameter" keyword (not a tool)
                if tool_name == "parameter":
                    continue

                # Find the params block after this specific tool name occurrence
                # Match the tool name line and grab everything until the next tool name
                param_pattern = re.compile(
                    r'<tool_call:[a-f0-9]+>' + re.escape(tool_name) +
                    r'(.*?)(?=<tool_call:|</tool_calls:|$)',
                    re.DOTALL,
                )
                param_match = param_pattern.search(block)

                args = {}
                if param_match:
                    params_block = param_match.group(1)
                    param_re = re.compile(
                        r'parameter name="([^"]+)">(.*?)(?=<tool_call:|$)',
                        re.DOTALL,
                    )
                    for pm in param_re.finditer(params_block):
                        args[pm.group(1)] = pm.group(2).strip()

                tool_calls.append(
                    {
                        "id": f"tc_{tc_id}_{len(tool_calls)}",
                        "name": tool_name,
                        "args": args,
                    }
                )

    # Parse standard `` format
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

    if not tool_calls:
        # Also handle mid-response missing closing tags (hy3-free often omits </tool_calls:ID>)
        # If we still have a <tool_call:> prefix, try a lenient fallback that tolerates
        # unclosed blocks by scanning for any known tool names.
        if re.search(r"<tool_calls?:[a-f0-9]+>", text):
            # Lenient fallback: extract any <tool_call:HEX>TOOLNAME occurrences as bare calls
            from ..tools.registry import registry as _reg

            known = set(_reg.tools.keys()) if _reg.tools else set()
            # Find all tool names in alternate format even without proper wrapper close
            fallback_names = re.findall(r"<tool_call:[a-f0-9]+>(\w+)", text)
            made = []
            for nm in fallback_names:
                if nm == "parameter":
                    continue
                if known and nm not in known:
                    continue
                if nm and nm not in [c["name"] for c in made]:
                    made.append({"id": f"tc_fallback_{nm}_{len(made)}", "name": nm, "args": {}})
            if made:
                logger.info(f"Fallback parsed {len(made)} tool calls from unclosed XML (lenient mode)")
                cleaned = re.sub(r"<tool_calls?:[a-f0-9]+>.*", "", text, flags=re.DOTALL).strip()
                cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", cleaned, flags=re.DOTALL).strip()
                return cleaned, made
            logger.warning(
                "Found <tool_call:> XML in response but _parse_text_tool_calls "
                "could not parse it — tool calls will be sent as raw text"
            )
        return text, []

    # Clean both formats from text (handle with and without closing tags)
    # Handle mid-response unclosed blocks: cut from first wrapper to end if no close
    cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL).strip()
    cleaned = re.sub(
        r"<tool_calls?:[a-f0-9]+>.*?(?:</tool_calls?:[a-f0-9]+>|\Z)",
        "",
        cleaned,
        flags=re.DOTALL,
    ).strip()
    # Also strip any remaining lenient fragments "<tool_call:HEX>name …" without close
    cleaned = re.sub(r"<tool_call:[a-f0-9]+>.*", "", cleaned, flags=re.DOTALL).strip()
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
    """Heuristic: is this failure worth retrying?

    Separate from ToolResult.ok — ok says failure happened; this decides
    whether a retry is sensible based on error text / known transient hints.
    """
    r = (result or "").lower()
    return any(hint in r for hint in _RETRYABLE_ERROR_HINTS)


def _execute_tool_with_retry(tool_name: str, tool_args: dict, tool_id: str):
    """Execute a tool via ``execute_result``, retrying transient failures.

    ``ToolResult.ok`` is authoritative for success/failure.
    Transient detection uses error/observation text only when ok is False.
    Destructive tools are never retried.

    Returns:
        ToolResult — callers use ``.ok`` for control flow and ``to_llm_text()``
        for the LLM observation.
    """
    from ..tools.result import ToolResult

    if _tool_is_destructive(tool_name, tool_args):
        return registry.execute_result(tool_name, tool_args)

    last: ToolResult | None = None
    for attempt in range(1, TOOL_RETRY_LIMIT + 1):
        tr = registry.execute_result(tool_name, tool_args)
        last = tr
        if tr.ok:
            return tr
        # Failure: decide retry from error/observation text, not by
        # reconstructing success from string prefixes alone.
        err_text = tr.error if tr.error is not None else tr.to_llm_text()
        if not _is_transient_error(str(err_text)):
            return tr
        logger.warning(
            f"Tool '{tool_name}' transient failure "
            f"(attempt {attempt}/{TOOL_RETRY_LIMIT}), retrying: {str(err_text)[:80]}"
        )
        if attempt < TOOL_RETRY_LIMIT:
            time.sleep(min(2 ** attempt, 8))

    assert last is not None
    if not last.ok:
        logger.error(
            f"Tool '{tool_name}' failed after {TOOL_RETRY_LIMIT} attempts: "
            f"{last.to_llm_text()[:200]}"
        )
    return last


# ── Thread-local state ────────────────────────────────────
from .emit_context import _get_emit, _set_emit, get_emit, set_emit  # noqa: F401


def _ensure_tracer_store():
    """Bind the memory store to the tracer once. Best-effort; never raises."""
    try:
        if tracer._store is None:
            from ..memory import memory_store

            tracer.set_store(memory_store)
    except Exception:
        pass


# ── Approval gate ─────────────────────────────────────────
# Approvals are persisted to SQLite via _save_pending_approval / _get_approval_status.
# The tool_execution_node polls SQLite at 2-second intervals instead of blocking on
# threading.Event, so the web server thread pool is never starved (audit Risk #1).
# Cross-process resolution (Telegram bot → web server) works via SQLite WAL.


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


def _has_duplicate_tool_calls(messages: list, window: int = 10) -> bool:
    """Detect doom loops — same tool with same args called repeatedly.

    Checks full message history (not just last 6) and hashes
    ``tool_name + sorted(args)``.  Threshold is DUPLICATE_TOOL_THRESHOLD
    (default 3) so 3 identical calls across 10 messages triggers.
    This mirrors Vibe's loop detector and avoids the previous
    impossible case (threshold 10 in window 6 with 1 call/msg).
    """
    # Dynamic threshold: never allow impossible case (threshold > window)
    effective_threshold = min(DUPLICATE_TOOL_THRESHOLD, max(2, window))
    seen = {}
    for msg in messages[-window:] if window else messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                # Support both dict and object forms
                if isinstance(tc, dict):
                    name = tc.get("name", "")
                    args = tc.get("args", {})
                else:
                    # langchain tool_calls can be dict-like with attribute access
                    try:
                        name = tc["name"] if "name" in tc else getattr(tc, "name", "")
                    except Exception:
                        name = getattr(tc, "name", "")
                    try:
                        args = tc["args"] if "args" in tc else getattr(tc, "args", {})
                    except Exception:
                        args = {}
                try:
                    key = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=True)}"
                except Exception:
                    key = f"{name}:{str(args)}"
                seen[key] = seen.get(key, 0) + 1
                if seen[key] >= effective_threshold:
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
    session_id: str  # stable brain identity (not fresh_thread)
    plan: Optional[Dict[str, Any]]
    plan_status: str
    step_results: Dict[str, str]
    current_step_index: int
    model_override: Optional[str]
    start_time: float
    tool_failures: List[Dict[str, Any]]
    intent_class: str
    intent_confidence: float
    strategy: str  # TaskRouter decision: direct|react|plan|delegate|engineering
    route_decision: Optional[Dict[str, Any]]
    wall_time_budget: int
    task_progress: Dict[str, str]


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
        # Clear collected content so tool call text isn't sent as response
        collected_content.clear()

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
        if "model is not supported" in error_str or "modelerror" in error_str or "model not found" in error_str:
            raise LLMError.model_not_found(provider="llm", model=str(last_error)[:120])
        elif "429" in error_str or "rate" in error_str:
            raise LLMError.rate_limit(provider="llm")
        elif "overloaded" in error_str or "503" in error_str:
            raise LLMError.overloaded(provider="llm")
        elif "auth" in error_str or "401" in error_str:
            raise LLMError.auth_failed(provider="llm")
        else:
            raise LLMError.connection_failed(provider="llm", reason=str(last_error)[:200])


def _detect_partial_completion(state: AgentState) -> str:
    """Detect partial completion scenarios that should prevent honest success claims.

    Returns a reason string if partial completion detected, empty string otherwise.
    Only checks per-turn state (resets between turns), NOT message history.
    Only blocks if failures dominate (>50%) or ALL tools failed.
    """
    # Check for failed tools in task_progress
    task_progress = state.get("task_progress", {})
    failed_tools = [tool for tool, status in task_progress.items() if status == "failed"]
    succeeded_tools = [tool for tool, status in task_progress.items() if status == "success"]
    total_tracked = len(failed_tools) + len(succeeded_tools)

    if failed_tools:
        # Only block if failures dominate or nothing succeeded
        if total_tracked == 0 or len(failed_tools) >= total_tracked or len(failed_tools) / total_tracked > 0.5:
            return f"tool failures: {', '.join(failed_tools)}"
        # Otherwise, partial success — don't block

    # Check if wall-clock budget is >80% consumed
    start_time = state.get("start_time", 0)
    wall_budget = state.get("wall_time_budget", 300)
    if start_time and wall_budget:
        elapsed = time.time() - start_time
        if elapsed > wall_budget * 0.8:
            return f"wall-clock budget {int(elapsed)}s/{wall_budget}s (>80% consumed)"

    return ""


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
            from openai.types.chat import ChatCompletionMessageToolCall

            assistant_msg.tool_calls = [
                ChatCompletionMessageToolCall(
                    id=tc["id"],
                    type="function",
                    function={"name": tc["name"], "arguments": json.dumps(tc["args"])},
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
            # ── Completion gate ──
            # Only force "not complete" if tool failures are significant
            # (all or most calls failed). Partial failures on a mostly-successful
            # turn should not block the response.
            failures = state.get("tool_failures", [])
            partial = _detect_partial_completion(state)
            total_calls = state.get("tool_calls_total", 0)
            failure_count = len(failures)
            _should_block = False
            if partial:
                _should_block = True
            elif failure_count > 0 and total_calls > 0:
                # Block only if ALL calls failed or failures dominate (>50%)
                _should_block = failure_count >= total_calls or (failure_count / total_calls) > 0.5
            elif failure_count > 0 and total_calls == 0:
                # No total count tracked — block on any failure (legacy safety)
                _should_block = True
            if _should_block:
                if failures:
                    _summary = "\n".join(
                        f"- {f.get('tool')}: {f.get('error', '')[:160]}" for f in failures[-6:]
                    )
                    _reason = (
                        "The following tool call(s) failed this turn "
                        "and were not resolved:\n"
                        + _summary
                    )
                else:
                    _reason = f"Partial completion detected: {partial}"
                ai_message.content = (
                    "[TASK NOT COMPLETE] " + _reason
                    + "\n\nI have not finished. Tell me how you'd like to proceed."
                )
                logger.warning(f"Completion gate: forcing incomplete status ({len(failures)} failures, partial: {partial or 'none'})")
                return {
                    "messages": [ai_message],
                    "iteration": iteration + 1,
                    "error_count": 0,
                    "last_error": None,
                    "tool_failures": [],
                }
        except Exception as e:
            logger.warning(f"Claim verification failed: {e}")

    # ── Output Guardrails ──
    if ai_message.content and not ai_message.tool_calls:
        try:
            from .guardrails import guardrail_engine
            output_results = guardrail_engine.check_output(
                ai_message.content,
                context={
                    "receipts": [r for r in (receipt_store.get_recent(limit=20) if 'receipt_store' in dir() else [])],
                    "failed_tools": [f.get("tool") for f in state.get("tool_failures", [])],
                },
            )
            if guardrail_engine.should_block(output_results):
                for r in output_results:
                    if r.verdict.value == "block":
                        ai_message.content = f"[Blocked by guardrail] {r.message}"
                        break
            else:
                # Apply any modifications
                ai_message.content = guardrail_engine.get_modified_content(output_results, ai_message.content)
                # Log warnings
                for r in output_results:
                    if r.verdict.value == "warn":
                        logger.warning(f"Output guardrail warning: {r.message}")
        except Exception as e:
            logger.debug(f"Output guardrails skipped: {e}")

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
    # Per-turn record of failed tool calls (consumed by the completion gate in
    # the generate_response node and reset there after each final answer).
    failure_log = []
    # Per-turn record of tool execution outcomes for task_progress tracking.
    progress_log = []

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

    # ── Checkpoint: begin turn (vibe-style) ──
    _ckpt_turn_id = state.get("iteration", 0) + 1
    if checkpointer is not None:
        try:
            # Don't double-open if previous turn leaked
            if not checkpointer.has_open_turn():
                checkpointer.begin_turn(_ckpt_turn_id)
        except Exception as _e:
            logger.debug(f"Checkpoint begin_turn skipped: {_e}")

    def _ckpt_record_pre(tool_name: str, tool_args: dict):
        """Capture before-state for checkpoint."""
        if checkpointer is None or checkpoint_store is None:
            return
        try:
            paths: list[str] = []
            if tool_name == "file_ops":
                act = tool_args.get("action")
                if act in ("write", "delete") and tool_args.get("file_path"):
                    paths.append(tool_args["file_path"])
                elif act in ("move", "copy") and tool_args.get("file_path"):
                    paths.append(tool_args["file_path"])
                    if tool_args.get("destination"):
                        paths.append(tool_args["destination"])
                elif act == "mkdir" and tool_args.get("file_path"):
                    paths.append(tool_args["file_path"])
            elif tool_name in ("run_command", "run_code", "code_analysis"):
                # run_command snapshot is coarse; record at least cwd files via project diff later
                pass
            # Also capture any explicit file_path/content path
            elif tool_args.get("file_path"):
                paths.append(tool_args["file_path"])
            for p in paths:
                if not p:
                    continue
                # Normalize to absolute where possible
                try:
                    ap = str(Path(p).resolve()) if Path(p).is_absolute() else str((Path.cwd() / p).resolve())
                except Exception:
                    ap = p
                # Avoid capturing huge binary or sensitive paths
                if any(seg in ap for seg in (".git", "__pycache__", "node_modules", ".venv")):
                    continue
                st = checkpoint_store.read(ap)
                # Also record the logical path the tool used (so restore works even if cwd changed)
                checkpointer.record_pre(p, st)
                if ap != p:
                    checkpointer.record_pre(ap, st)
        except Exception as _e:
            logger.debug(f"Checkpoint record_pre skipped: {_e}")

    def _ckpt_record_post(tool_name: str, tool_args: dict):
        """Capture after-state for checkpoint."""
        if checkpointer is None or checkpoint_store is None:
            return
        try:
            paths: list[str] = []
            if tool_name == "file_ops":
                act = tool_args.get("action")
                if act in ("write", "delete") and tool_args.get("file_path"):
                    paths.append(tool_args["file_path"])
                elif act in ("move", "copy"):
                    if tool_args.get("file_path"):
                        paths.append(tool_args["file_path"])
                    if tool_args.get("destination"):
                        paths.append(tool_args["destination"])
                elif act == "mkdir" and tool_args.get("file_path"):
                    paths.append(tool_args["file_path"])
            elif tool_args.get("file_path"):
                paths.append(tool_args["file_path"])
            for p in paths:
                if not p:
                    continue
                try:
                    ap = str(Path(p).resolve()) if Path(p).is_absolute() else str((Path.cwd() / p).resolve())
                except Exception:
                    ap = p
                if any(seg in ap for seg in (".git", "__pycache__", "node_modules", ".venv")):
                    continue
                st = checkpoint_store.read(ap)
                checkpointer.record_post(p, st)
                if ap != p:
                    checkpointer.record_post(ap, st)
        except Exception as _e:
            logger.debug(f"Checkpoint record_post skipped: {_e}")

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

        # ── Hooks: PreToolUse (deterministic, can deny even bypass) ──
        try:
            from ..core.hooks.manager import get_hook_manager

            _hook_pre = get_hook_manager().run_pre_tool(tool_name, tool_args)
            if _hook_pre.decision == "deny":
                logger.info(f"Hook denied: {tool_name} -> {_hook_pre.reason}")
                _finish(False, f"denied by hook: {_hook_pre.reason}")
                return ToolMessage(
                    content=f"Blocked by hook '{_hook_pre.reason or 'PreToolUse deny'}': {tool_name} denied.",
                    tool_call_id=tool_id,
                )
        except Exception as _e:
            logger.debug(f"PreTool hook skipped: {_e}")

        decision = permission_gate.check(tool_name, tool_args)

        # ── Tool Guardrails ──
        try:
            from .guardrails import guardrail_engine
            tool_results = guardrail_engine.check_tool(tool_name, tool_args)
            if guardrail_engine.should_block(tool_results):
                blocked_msg = f"Tool '{tool_name}' blocked by guardrail: "
                for r in tool_results:
                    if r.verdict.value == "block":
                        blocked_msg += r.message
                        break
                _finish(False, "blocked by guardrail")
                return ToolMessage(content=blocked_msg, tool_call_id=tool_id)
        except Exception as e:
            logger.debug(f"Tool guardrails skipped: {e}")

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
                _save_pending_approval(tool_id, "pending")

                # Compute diff preview for file write operations
                diff = _compute_file_diff(tool_args)

                approved = False
                result_approved = False

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
                    # No emit — approval buttons cannot appear (e.g. headless, CLI, or
                    # same-process webhook where the bot handles its own emit).
                    # Auto-approve so the agent doesn't block for 30 minutes.
                    logger.info(f"approval_gate: emit is None for '{tool_name}' — auto-approving (no UI for buttons)")
                    _save_pending_approval(tool_id, "approved")
                    approved = True
                    result_approved = True

                if not approved:
                    logger.info(f"Approval gate: waiting for user confirmation of '{tool_name}' (timeout: {APPROVAL_TIMEOUT}s)")

                    # Poll SQLite every 2s — no thread blocking, cross-process safe.
                    _poll_interval = 2
                    _polls = (APPROVAL_TIMEOUT or 1800) // _poll_interval
                    for _i in range(_polls):
                        if _check_abort(thread_id):
                            _save_pending_approval(tool_id, "aborted")
                            _finish(False, "aborted by user")
                            return ToolMessage(content="Aborted by user.", tool_call_id=tool_id)
                        status = _get_approval_status(tool_id)
                        if status in ("approved", "denied"):
                            result_approved = (status == "approved")
                            approved = True
                            break
                        time.sleep(_poll_interval)

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

        # Checkpoint pre-state capture
        _ckpt_record_pre(tool_name, tool_args)

        start = time.time()
        try:
            _tr = _execute_tool_with_retry(tool_name, tool_args, tool_id)
            result = _tr.to_llm_text()
            success = _tr.ok  # ToolResult.ok is authoritative
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
        # Record FULL length for truth (receipt_store handles its own cap)
        # but ensure verifier sees error signals not truncated at 2k when possible.
        try:
            from ..tools.receipts import receipt_store

            # Keep at least 8000 for evidence preservation (previous 2000 hid Error: prefix)
            _receipt_text = str(result)
            if len(_receipt_text) > 8000:
                _receipt_text = _receipt_text[:8000] + f"\n... [truncated {len(str(result))} → 8000 chars]"
            receipt_store.record(
                tool_call_id=tool_id,
                tool=tool_name,
                args=tool_args,
                result=_receipt_text[:8000],
                success=success,
                duration_ms=duration,
            )
        except Exception as e:
            logger.warning(f"Failed to record receipt for {tool_name}: {e}")

        # ── Post-execution validation ──────────────────────
        # Verify tool output matches claimed success before reporting to agent.
        # Success is now derived authoritatively (registry._result_is_success):
        # Error:-prefixed results and non-zero run_command exits are failures.
        # Here we only flag UNMISTAKABLE crash signals (a leaked Python
        # traceback / exception type) as a defense-in-depth net. We deliberately
        # do NOT sniff for loose words like "error"/"failed"/"not found" — those
        # appear constantly in legitimate file content and command output and
        # produced false-positive "success" downgrades. File-content tools are
        # exempt entirely; their success is already structural.
        if success and isinstance(result, str) and tool_name not in ("read_file", "file_ops"):
            _HARD_ERROR_TOKENS = (
                "traceback (most recent call last)",
                "permissionerror:",
                "filenotfounderror:",
                "modulenotfounderror:",
                "isadirectoryerror:",
                "notadirectoryerror:",
                "oserror:",
                "valueerror:",
                "timeouterror:",
                "connectionerror:",
                "keyerror:",
                "typeerror:",
            )
            rl = result.lower()
            is_hard_error = any(tok in rl for tok in _HARD_ERROR_TOKENS)
            if is_hard_error:
                logger.warning(f"Tool validation: {tool_name} reported success but output contains error patterns")
                success = False
                result += "\n\n[Validation warning: output contains error-like text despite success status]"
            elif not result.strip():
                logger.warning(f"Tool validation: {tool_name} reported success but output is empty")
                result = "(empty result — tool executed but produced no output)"

        # ── Harness v2: Tool-Result Verification (Phase 4) ──
        try:
            from ..config import HARNESS_ENABLED, HARNESS_VERIFY_ENABLED, HARNESS_SCRATCHPAD_ENABLED
            if HARNESS_ENABLED and HARNESS_VERIFY_ENABLED:
                from .harness import verify_tool_result, _TOOL_VERIFY_MAX_RETRIES
                # Get objective from state if available
                _objective = ""
                _intent = state.get("intent_class", "")
                if _intent in ("COMPLEX", "CREATIVE", "HIGH_STAKES"):
                    # Try to extract objective from the last human message
                    for msg in reversed(state.get("messages", [])):
                        if hasattr(msg, "content") and msg.content and not hasattr(msg, "tool_calls"):
                            _objective = msg.content[:200]
                            break

                verification = verify_tool_result(
                    tool_name=tool_name,
                    tool_args=tool_args if isinstance(tool_args, dict) else {},
                    tool_result=str(result),
                    tool_success=success,
                    objective=_objective,
                )
                if not verification.satisfies_objective and success:
                    logger.warning(
                        f"Tool verification: {tool_name} passed but may not satisfy objective "
                        f"(confidence={verification.confidence:.2f})"
                    )
                    if emit:
                        try:
                            emit("tool_verification", verification.to_dict())
                        except Exception:
                            pass

            # ── Harness v2: Scratchpad update after tool ──
            if (
                HARNESS_ENABLED
                and HARNESS_SCRATCHPAD_ENABLED
                and "_scratchpad" in state
                and state["_scratchpad"]
            ):
                _sp = state["_scratchpad"]
                if tool_success:
                    _sp.add_action(tool_name, str(tool_args)[:100])
                    _sp.add_result(str(result)[:200])
                else:
                    _sp.add_action(tool_name, str(tool_args)[:100], error=True)
                state["_scratchpad"] = _sp
        except Exception as e:
            logger.debug(f"Tool verification skipped: {e}")

        # ── Hooks: PostToolUse (can append additionalContext) ──
        try:
            from ..core.hooks.manager import get_hook_manager

            _hook_post = get_hook_manager().run_post_tool(tool_name, tool_args, str(result), success)
            if _hook_post.additionalContext:
                # Append hook context to result so LLM sees it next turn
                result = str(result) + "\n\n[Hook] " + _hook_post.additionalContext
                logger.info(f"Hook PostTool appended context for {tool_name}: {_hook_post.additionalContext[:120]}")
        except Exception as _e:
            logger.debug(f"PostTool hook skipped: {_e}")

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
                # Emit cap raised from 500 to 2000 for richer UI without truncation cascade.
                # Keep IMAGE_FILE tail optimization.
                result_str = str(result)
                _EMIT_CAP = 2000
                if len(result_str) > _EMIT_CAP:
                    if "IMAGE_FILE:" in result_str:
                        result_str = "..." + result_str[-_EMIT_CAP + 3 :]
                    else:
                        result_str = result_str[:_EMIT_CAP] + f"\n... [truncated {len(str(result))} → {_EMIT_CAP} chars]"
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

        if not success:
            failure_log.append({
                "tool": tool_name,
                "args": tool_args if isinstance(tool_args, dict) else {},
                "error": str(result)[:200],
            })
            progress_log.append({"tool": tool_name, "status": "failed"})
        else:
            progress_log.append({"tool": tool_name, "status": "success"})

        # Checkpoint post-state capture
        _ckpt_record_post(tool_name, tool_args)

        # ── Auto-save task state on ALL tool calls ──
        # Track files created, read, and executed so Nally can resume without re-reading everything.
        if success:
            try:
                from ..tools.task_state import task_state_manager, TaskState
                from ..config import SESSION_ID

                # Brain session_id (stable), not LangGraph fresh_thread and not
                # process-wide SESSION_ID alone — matches NallyAgent._session_id.
                brain_id = state.get("session_id") or SESSION_ID
                task_st = task_state_manager.get(brain_id)
                if not task_st:
                    task_st = TaskState(brain_id)
                    task_st.task_description = "Auto-tracked work"

                args = tool_args if isinstance(tool_args, dict) else {}
                fp = args.get("file_path", "")
                action = args.get("action", "")

                if tool_name == "file_ops":
                    if action == "write" and fp:
                        if fp not in task_st.files_created:
                            task_st.files_created.append(fp)
                        task_st.current_step = f"Wrote {fp}"
                        task_st.last_tool_result = f"Created: {fp}"
                    elif action == "delete" and fp:
                        if fp in task_st.files_created:
                            task_st.files_created.remove(fp)
                        task_st.current_step = f"Deleted {fp}"

                elif tool_name == "read_file" and fp:
                    tag = f"read:{fp}"
                    if tag not in task_st.key_decisions:
                        task_st.key_decisions.append(tag)
                    task_st.current_step = f"Read {fp}"

                elif tool_name == "execute":
                    code = args.get("code", "")[:100]
                    task_st.current_step = f"Executed code: {code}..."
                    task_st.last_tool_result = str(result)[:200]

                elif tool_name in ("design_fetch", "design_sources"):
                    task_st.current_step = f"Fetched from {tool_name}: {args.get('category', '')}"
                    task_st.last_tool_result = str(result)[:200]

                elif tool_name == "web_search":
                    task_st.current_step = f"Searched: {args.get('query', '')}"
                    task_st.last_tool_result = str(result)[:200]

                elif tool_name == "task_state":
                    pass

                else:
                    task_st.current_step = f"Used {tool_name}"

                task_state_manager.save(task_st)
            except Exception as e:
                logger.debug(f"Auto-save task state skipped: {e}")

        # Return up to MAX_TOOL_OUTPUT (50k) for LLM truth; registry already capped.
        # Previous 2000 hid evidence from next LLM turn + verifier.
        _finish(success, str(result)[:MAX_TOOL_OUTPUT])
        return ToolMessage(content=str(result)[:MAX_TOOL_OUTPUT], tool_call_id=tool_id)

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

    base_ctx = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=min(len(last_ai_msg.tool_calls), 5)) as executor:
        # Each thread gets its own context copy — reusing the same ctx across
        # threads causes "context already entered" errors.
        futures = {
            executor.submit(base_ctx.copy().run, _execute_single, tc): tc
            for tc in last_ai_msg.tool_calls
        }
        for future in as_completed(futures):
            try:
                tool_messages.append(future.result())
            except Exception as e:
                tc = futures[future]
                tool_messages.append(ToolMessage(content=f"Error: {e!s}", tool_call_id=tc["id"]))

    # Seal checkpoint turn (best-effort, never crash agent)
    if checkpointer is not None:
        try:
            checkpointer.seal_turn()
        except Exception as _e:
            logger.debug(f"Checkpoint seal_turn skipped: {_e}")

    return {
        "messages": tool_messages,
        "tool_calls_total": tool_calls_total + len(last_ai_msg.tool_calls),
        "tool_failures": state.get("tool_failures", []) + [
            {"tool": f["tool"], "args": f["args"], "error": f["error"]} for f in failure_log
        ],
        "task_progress": {
            **state.get("task_progress", {}),
            **{p["tool"]: p["status"] for p in progress_log},
        },
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
    wall_budget = state.get("wall_time_budget", MAX_AGENT_WALL_TIME)
    if start_time and (time.time() - start_time) > wall_budget:
        logger.warning(f"Agent exceeded {wall_budget}s wall-clock budget")
        emit = _get_emit()
        if emit:
            try:
                _fail_n = len(state.get("tool_failures", []))
                _notice = (
                    f"Execution halted: hit my {wall_budget}s time budget for this turn"
                )
                if _fail_n:
                    _notice += (
                        f" — {_fail_n} tool call(s) failed and weren't resolved. Say 'continue' "
                        "and I'll pick up where I left off using what we have."
                    )
                else:
                    _notice += " — say 'continue' if you want me to keep going."
                emit("system_notice", {"text": _notice})
            except Exception:
                pass
        _record_exit("wall_clock")
        return "end"

    # Too many failed tool calls this turn — halt and ask the user how to proceed
    # instead of looping on a failing action and burning the wall-clock budget.
    if len(state.get("tool_failures", [])) >= MAX_TOOL_FAILURES_PER_TURN:
        logger.warning(f"Agent exceeded {MAX_TOOL_FAILURES_PER_TURN} tool failures this turn")
        emit = _get_emit()
        if emit:
            try:
                emit("system_notice", {
                    "text": f"Execution halted: {MAX_TOOL_FAILURES_PER_TURN}+ tool calls failed this turn and weren't resolved. Tell me how you'd like to proceed."
                })
            except Exception:
                pass
        _record_exit("tool_failures")
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
        planner -> critique -> (execute_step | planner)
        execute_step -> replan -> (execute_step | planner | synthesize | llm)
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
            critique_node,
            execute_step_node,
            planner_node,
            replan_node,
            route_after_classify,
            route_after_critique,
            route_after_replan,
            synthesize_node,
        )
        from .human_checkpoint import human_checkpoint_node

        graph.add_node("classify", classify_node)
        graph.add_node("planner", planner_node)
        graph.add_node("critique", critique_node)
        graph.add_node("human_checkpoint", human_checkpoint_node)
        graph.add_node("execute_step", execute_step_node)
        graph.add_node("replan", replan_node)
        graph.add_node("synthesize", synthesize_node)

        # classify decides: planner or ReAct?
        graph.add_conditional_edges(
            "classify",
            route_after_classify,
            {"planner": "planner", "llm": "llm"},
        )

        # planner -> critique (review before execution)
        graph.add_edge("planner", "critique")

        # critique routes: revise plan or proceed to human checkpoint
        graph.add_conditional_edges(
            "critique",
            route_after_critique,
            {"execute_step": "human_checkpoint", "planner": "planner"},
        )

        # human_checkpoint -> execute_step (after user approves)
        graph.add_edge("human_checkpoint", "execute_step")

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
    intent_class: str = "",
    intent_confidence: float = 0.0,
    route_decision: Any = None,
) -> str:
    """Run the agent graph and return the final response.

    When core supplies the authoritative RouteDecision, it is seeded into
    initial state so classify_node consumes it instead of routing again.
    """
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

    # Wrap emit in typed emitter for projection support
    from .streaming import EventEmitter
    _emitter = EventEmitter(emit_fn=emit)

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

    # Authoritative route decision from core (typed RouteDecision or dict).
    # Kept typed as long as practical; only dict crosses the graph boundary.
    _supplied_strategy = ""
    _supplied_decision_dict = None
    if route_decision is not None:
        try:
            to_dict = getattr(route_decision, "to_dict", None)
            if callable(to_dict):
                _supplied_decision_dict = to_dict()
            elif isinstance(route_decision, dict):
                _supplied_decision_dict = route_decision
            strat = _supplied_decision_dict.get("strategy") if _supplied_decision_dict else None
            if strat is not None:
                _supplied_strategy = strat.value if hasattr(strat, "value") else str(strat)
        except Exception:
            _supplied_decision_dict = None
            _supplied_strategy = ""

    initial_state = {
        "messages": lc_messages,
        "tools": tools,
        "iteration": 0,
        "max_iterations": max_iterations,
        "error_count": 0,
        "last_error": None,
        "tool_calls_total": 0,
        "thread_id": fresh_thread,
        "session_id": thread_id,  # canonical brain id for TaskState / cross-channel
        "plan": None,
        "plan_status": "",
        "step_results": {},
        "current_step_index": 0,
        "model_override": model,
        "start_time": time.time(),
        "tool_failures": [],
        "intent_class": intent_class,
        "intent_confidence": intent_confidence,
        "strategy": _supplied_strategy,  # consumed by classify_node; empty = back-compat re-route once
        "route_decision": _supplied_decision_dict,
        "wall_time_budget": WALL_TIME_OVERRIDES.get(intent_class, MAX_AGENT_WALL_TIME) if intent_class else MAX_AGENT_WALL_TIME,
        "task_progress": {},
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

        # Fallback: strip any residual XML tool call tags that leaked through
        # This is defense-in-depth — the user should never see raw XML
        if chain_response and re.search(r"<tool_calls?:[a-f0-9]+>", chain_response):
            logger.warning("Residual XML tool call tags found in final response — stripping")
            chain_response = re.sub(
                r"<tool_calls?:[a-f0-9]+>.*?(?:</tool_calls?:[a-f0-9]+>|$)",
                "",
                chain_response,
                flags=re.DOTALL,
            ).strip()

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

    Persists decision to SQLite — the polling tool_execution_node picks it up
    on the next 2-second interval. Returns True always (resolution is async).
    """
    status_str = "approved" if approved else "denied"
    _save_pending_approval(tool_call_id, status_str)
    logger.info(f"resolve_approval: tc_id={tool_call_id}, approved={approved}")
    return True
