"""Nally Agent Graph - LangGraph-based agent loop

State machine using LangGraph. ReAct pattern:
Think -> Use Tool -> Observe -> Think -> ... -> Finish
"""
import difflib
import glob
import json
import os
import re
import threading
import time
from typing import TypedDict, Annotated, List, Dict, Any, Optional
from pathlib import Path
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import (
    BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage,
)
from ..tools.registry import registry
from ..tools.permissions import gate as permission_gate
from ..core.errors import LLMError, ToolError, PermissionDenied
from ..config import DATABASE_URL, ensure_data_dir
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

        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        ))

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
    except Exception:
        pass
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
                        diff = list(difflib.unified_diff(
                            [], new_content.splitlines(keepends=True),
                            fromfile=f"a/{fp}", tofile=f"b/{fp}", lineterm="",
                        ))
                        if diff:
                            results.append((fp, "".join(diff)))
                    elif old[0] != p.stat().st_mtime:
                        # Modified file
                        diff = list(difflib.unified_diff(
                            old[1].splitlines(keepends=True),
                            new_content.splitlines(keepends=True),
                            fromfile=f"a/{fp}", tofile=f"b/{fp}", lineterm="",
                        ))
                        if diff:
                            results.append((fp, "".join(diff)))
                except (PermissionError, OSError, UnicodeDecodeError):
                    pass
    except Exception:
        pass
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
                tool_calls.append({
                    "id": f"tc_{name}_{len(tool_calls)}",
                    "name": name,
                    "args": args if isinstance(args, dict) else {},
                })
        except json.JSONDecodeError:
            continue
    cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL).strip()
    return cleaned, tool_calls


# ── Circuit breaker settings ──────────────────────────────
MAX_CONSECUTIVE_ERRORS = 5
MAX_TOOL_CALLS = 50
_MAX_RETRIES = 3
_RETRYABLE_CODES = {"500", "502", "503", "429"}

# ── Thread-local state ────────────────────────────────────
_tlocal = threading.local()

def _get_emit():
    return getattr(_tlocal, "emit", None)

def _set_emit(emit):
    _tlocal.emit = emit

# ── Approval gate ─────────────────────────────────────────
_approval_events: Dict[str, threading.Event] = {}
_approval_results: Dict[str, bool] = {}


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    tools: List[Dict[str, Any]]
    iteration: int
    max_iterations: int
    error_count: int
    last_error: Optional[str]
    tool_calls_total: int
    thread_id: str


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
            openai_messages.append({
                "role": "tool",
                "tool_call_id": msg.tool_call_id,
                "content": msg.content,
            })
    return openai_messages


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
        assistant_msg = ChatCompletionMessage(
            role="assistant", content=full_content or "", tool_calls=tc_list
        )
    else:
        assistant_msg = ChatCompletionMessage(role="assistant", content=full_content)

    return ChatCompletion(
        id="stream",
        choices=[Choice(finish_reason="stop", index=0, message=assistant_msg)],
        created=0,
        model="",
        object="chat.completion",
    )


def _call_llm_with_retry(llm_client, openai_messages, tools, cache_key, emit):
    """Call LLM with streaming + retry. Raises LLMError on failure."""
    last_error = None
    for attempt in range(_MAX_RETRIES):
        try:
            if emit:
                try:
                    return _stream_with_emit(llm_client, openai_messages, tools, cache_key, emit)
                except Exception as stream_err:
                    logger.warning(f"Streaming failed, falling back: {stream_err}")
                    try:
                        emit("stream_done", {})
                    except Exception:
                        pass
            response = llm_client.chat(
                openai_messages, tools=tools if tools else None, cache_key=cache_key
            )
            return response

        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            is_retryable = any(code in error_str for code in _RETRYABLE_CODES)
            if attempt < _MAX_RETRIES - 1 and is_retryable:
                wait = min(2 ** (attempt + 1), 15)
                logger.warning(
                    f"LLM call failed (attempt {attempt + 1}/{_MAX_RETRIES}), "
                    f"retrying in {wait}s: {str(e)[:80]}"
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
            raise LLMError.connection_failed(provider="llm", detail=str(last_error)[:200])


def llm_call(state: AgentState) -> AgentState:
    """Call the LLM with current messages and tools."""
    from .llm import llm

    messages = state["messages"]
    tools = state["tools"]
    iteration = state.get("iteration", 0)
    error_count = state.get("error_count", 0)
    tool_calls_total = state.get("tool_calls_total", 0)
    cache_key = state.get("thread_id", "default")

    if error_count >= MAX_CONSECUTIVE_ERRORS:
        logger.warning(f"Circuit breaker: {error_count} consecutive errors, stopping agent")
        fallback = AIMessage(
            content="I've encountered repeated errors and need to stop. Please try again or rephrase your request."
        )
        return {"messages": [fallback], "iteration": iteration + 1, "error_count": 0}

    if tool_calls_total >= MAX_TOOL_CALLS:
        logger.warning(f"Circuit breaker: {tool_calls_total} total tool calls, stopping agent")
        # Make one final LLM call to summarize findings — no tools, no recursion
        try:
            summary_msgs = _convert_to_openai(messages) + [{
                "role": "system",
                "content": (
                    "You have reached the maximum number of tool calls. "
                    "Do NOT call any more tools. Instead, summarize everything you have found so far "
                    "based on the conversation history and tool results. Be thorough and specific — "
                    "reference actual findings, not generic placeholders."
                ),
            }]
            response = llm.chat(summary_msgs, tools=None, cache_key=cache_key)
            summary = response.choices[0].message.content or "I've reached the tool call limit. Here's what I found so far."
        except Exception as e:
            logger.warning(f"Circuit breaker summary call failed: {e}")
            summary = "I've reached the maximum number of tool calls. Please try again or rephrase your request."
        fallback = AIMessage(content=summary)
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

    try:
        response = _call_llm_with_retry(llm, openai_messages, tools, cache_key, emit)
    except LLMError as e:
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
                "args": json.loads(tc.function.arguments) if tc.function.arguments else {},
            }
            for tc in (assistant_msg.tool_calls or [])
        ]
        if assistant_msg.tool_calls
        else [],
    )

    if emit and assistant_msg.tool_calls:
        for tc in assistant_msg.tool_calls:
            try:
                emit("tool_call", {
                    "name": tc.function.name,
                    "args": json.loads(tc.function.arguments) if tc.function.arguments else {},
                    "iteration": iteration + 1,
                })
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

    last_ai_msg = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            last_ai_msg = msg
            break

    if not last_ai_msg:
        return {"messages": [], "tool_calls_total": tool_calls_total}

    def _execute_single(tc):
        tool_name = tc["name"]
        tool_args = tc["args"]
        tool_id = tc["id"]

        decision = permission_gate.check(tool_name, tool_args)

        if decision.value == "deny":
            logger.info(f"Permission denied: '{tool_name}' {tool_args}")
            return ToolMessage(
                content=f"Blocked: '{tool_name}' is denied by permission config.",
                tool_call_id=tool_id,
            )

        if decision.value == "ask":
            approval_event = threading.Event()
            _approval_events[tool_id] = approval_event

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
                    emit("confirmation_required", payload)
                except Exception:
                    pass

            logger.info(f"Approval gate: waiting for user confirmation of '{tool_name}'")
            approved = approval_event.wait(timeout=120)

            _approval_events.pop(tool_id, None)
            result_approved = _approval_results.pop(tool_id, False)

            if not approved or not result_approved:
                logger.info(f"Approval gate: user denied or timed out for '{tool_name}'")
                return ToolMessage(
                    content=f"Action '{tool_name}' was declined or timed out.",
                    tool_call_id=tool_id,
                )

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
            result = registry.execute(tool_name, tool_args)
        except Exception as e:
            result = f"Error executing {tool_name}: {str(e)}"
            logger.error_with_context(f"Tool {tool_name} failed", e)

        duration = (time.time() - start) * 1000
        logger.tool_call(tool_name, tool_args, result)

        # For run_command, detect changed files via snapshot diff
        if snapshot_before is not None and not str(result).startswith("Error"):
            changes = _diff_snapshots(snapshot_before)
            if changes:
                diff = "".join(d for _, d in changes)
                file_path_str = ", ".join(Path(fp).name for fp, _ in changes[:3])
                if len(changes) > 3:
                    file_path_str += f" +{len(changes) - 3} more"
                logger.info(f"Snapshot diff: {len(changes)} files changed")

        if emit:
            try:
                payload = {
                    "tool_call_id": tool_id,
                    "name": tool_name,
                    "result": str(result)[:500],
                    "duration_ms": round(duration),
                    "success": not str(result).startswith("Error"),
                }
                if diff:
                    payload["diff"] = diff
                    payload["file_path"] = file_path_str
                emit("tool_result", payload)
            except Exception:
                pass

        return ToolMessage(content=str(result)[:2000], tool_call_id=tool_id)

    tool_messages = []
    with ThreadPoolExecutor(max_workers=min(len(last_ai_msg.tool_calls), 5)) as executor:
        futures = {executor.submit(_execute_single, tc): tc for tc in last_ai_msg.tool_calls}
        for future in as_completed(futures):
            try:
                tool_messages.append(future.result())
            except Exception as e:
                tc = futures[future]
                tool_messages.append(ToolMessage(
                    content=f"Error: {str(e)}", tool_call_id=tc["id"]
                ))

    return {
        "messages": tool_messages,
        "tool_calls_total": tool_calls_total + len(last_ai_msg.tool_calls),
    }


def should_continue(state: AgentState) -> str:
    """Determine if we should continue the agent loop."""
    messages = state["messages"]
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 10)

    if iteration >= max_iterations:
        logger.debug(f"Agent reached max iterations ({max_iterations})")
        return "end"

    last_ai_msg = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            last_ai_msg = msg
            break

    if not last_ai_msg or not last_ai_msg.tool_calls:
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
    """Create the LangGraph state machine for the agent with checkpointing."""
    graph = StateGraph(AgentState)
    graph.add_node("llm", llm_call)
    graph.add_node("tools", tool_executor)
    graph.set_entry_point("llm")
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
) -> str:
    """Run the agent graph and return the final response."""
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
            lc_messages.append(ToolMessage(
                content=content, tool_call_id=msg.get("tool_call_id", "")
            ))

    _set_emit(emit)
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "messages": lc_messages,
        "tools": tools,
        "iteration": 0,
        "max_iterations": max_iterations,
        "error_count": 0,
        "last_error": None,
        "tool_calls_total": 0,
        "thread_id": thread_id,
    }

    try:
        graph = _get_graph()
        result = graph.invoke(initial_state, config=config)
        _set_emit(None)

        final_messages = result["messages"]
        for msg in reversed(final_messages):
            if isinstance(msg, AIMessage) and msg.content:
                return msg.content

        return "Done."

    except Exception as e:
        _set_emit(None)
        logger.error(f"Agent graph failed: {e}")
        raise


def resolve_approval(tool_call_id: str, approved: bool):
    """Resolve a pending approval request from the frontend."""
    event = _approval_events.get(tool_call_id)
    if event:
        _approval_results[tool_call_id] = approved
        event.set()
        logger.info(f"Approval resolved: tool_call_id={tool_call_id}, approved={approved}")
    else:
        logger.warning(f"Approval resolved for unknown tool_call_id: {tool_call_id}")
