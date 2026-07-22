"""Nally Agent Graph - LangGraph-based agent loop

This module replaces the manual tool calling loop in core.py with a
proper state machine using LangGraph. The agent follows the ReAct pattern:
Think -> Use Tool -> Observe -> Think -> ... -> Finish

Key benefits over the manual loop:
- Built-in state management
- Automatic tool_calls preservation
- Better error handling
- Checkpointing support (SQLite-backed)
- Circuit breaker for repeated failures
"""
import json
import operator
import threading
from typing import TypedDict, Annotated, List, Dict, Any, Optional
from pathlib import Path
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from ..tools.registry import registry
from ..utils.logger import logger

try:
    from ..tools.filter import tool_filter
except ImportError:
    class _StubFilter:
        _ready = False
        def build_index(self, tools): pass
        def select(self, query, **kw): return []
    tool_filter = _StubFilter()

# Circuit breaker settings
MAX_CONSECUTIVE_ERRORS = 5
MAX_TOOL_CALLS = 50

# Module-level emit callback (not in state to avoid serialization issues)
_current_emit = None

# Approval gate: pending approvals keyed by tool_call_id
_approval_events: Dict[str, threading.Event] = {}
_approval_results: Dict[str, bool] = {}


class AgentState(TypedDict):
    """State schema for the agent graph"""
    messages: Annotated[List[BaseMessage], add_messages]
    tools: List[Dict[str, Any]]
    iteration: int
    max_iterations: int
    error_count: int
    last_error: Optional[str]
    tool_calls_total: int
    thread_id: str


def llm_call(state: AgentState) -> AgentState:
    """Call the LLM with current messages and tools"""
    from .llm import llm
    
    messages = state["messages"]
    tools = state["tools"]
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 10)
    error_count = state.get("error_count", 0)
    tool_calls_total = state.get("tool_calls_total", 0)
    cache_key = state.get("thread_id", "default")
    
    # Circuit breaker: stop if too many consecutive errors
    if error_count >= MAX_CONSECUTIVE_ERRORS:
        logger.warning(f"Circuit breaker: {error_count} consecutive errors, stopping agent")
        fallback = AIMessage(content="I've encountered repeated errors and need to stop. Please try again or rephrase your request.")
        return {"messages": [fallback], "iteration": iteration + 1, "error_count": 0}
    
    # Circuit breaker: stop if too many total tool calls
    if tool_calls_total >= MAX_TOOL_CALLS:
        logger.warning(f"Circuit breaker: {tool_calls_total} total tool calls, stopping agent")
        fallback = AIMessage(content="I've reached the maximum number of tool calls for this session. Here's what I found so far.")
        return {"messages": [fallback], "iteration": iteration + 1}
    
    # Emit thinking event
    emit = _current_emit
    if emit and messages:
        last_msg = messages[-1]
        if hasattr(last_msg, "content") and last_msg.content:
            try:
                emit("thought", {"text": last_msg.content[:500]})
            except Exception:
                pass
    
    # Convert LangChain messages to OpenAI format
    openai_messages = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            openai_messages.append({"role": "system", "content": msg.content})
        elif isinstance(msg, HumanMessage):
            openai_messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            msg_dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"]) if isinstance(tc["args"], dict) else tc["args"]
                        }
                    }
                    for tc in msg.tool_calls
                ]
            openai_messages.append(msg_dict)
        elif isinstance(msg, ToolMessage):
            openai_messages.append({
                "role": "tool",
                "tool_call_id": msg.tool_call_id,
                "content": msg.content
            })
    
    # Call LLM with retry - always stream for faster perceived response
    last_error = None
    for attempt in range(3):
        try:
            if emit:
                # Try streaming first for faster perceived response
                try:
                    collected_content = []
                    collected_tool_calls = []
                    for event in llm.stream_chat_with_tools(openai_messages, tools=tools if tools else None, cache_key=cache_key):
                        if event["type"] == "content":
                            collected_content.append(event["text"])
                            try:
                                emit("stream_chunk", {"text": event["text"]})
                            except Exception:
                                pass
                        elif event["type"] == "tool_call":
                            collected_tool_calls.append(event)

                    # Signal streaming complete
                    try:
                        emit("stream_done", {})
                    except Exception:
                        pass

                    full_content = "".join(collected_content)

                    # Build response object
                    from openai.types.chat import ChatCompletion, ChatCompletionMessage
                    from openai.types.chat.chat_completion import Choice

                    if collected_tool_calls:
                        tc_list = [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc["args"]) if isinstance(tc["args"], dict) else json.dumps({})
                                }
                            }
                            for tc in collected_tool_calls
                        ]
                        assistant_msg = ChatCompletionMessage(
                            role="assistant",
                            content=full_content or "",
                            tool_calls=tc_list
                        )
                    else:
                        assistant_msg = ChatCompletionMessage(role="assistant", content=full_content)

                    response = ChatCompletion(
                        id="stream",
                        choices=[Choice(finish_reason="stop", index=0, message=assistant_msg)],
                        created=0, model="", object="chat.completion"
                    )
                except Exception as stream_err:
                    # Streaming failed — fall back to non-streaming
                    logger.warning(f"Streaming failed, falling back: {stream_err}")
                    try:
                        emit("stream_done", {})
                    except Exception:
                        pass
                    response = llm.chat(openai_messages, tools=tools if tools else None, cache_key=cache_key)
            else:
                # No emit callback - use non-streaming
                response = llm.chat(openai_messages, tools=tools if tools else None, cache_key=cache_key)
            last_error = None
            break
        except Exception as e:
            last_error = str(e)
            error_str = last_error.lower()
            if attempt < 2 and any(code in error_str for code in ["500", "502", "503", "overloaded", "429"]):
                import time
                wait = min(2 ** (attempt + 1), 15)
                logger.warning(f"LLM call failed (attempt {attempt + 1}/3), retrying in {wait}s: {last_error[:80]}")
                time.sleep(wait)
            else:
                break
    
    # If all retries failed, increment error count
    if last_error:
        new_error_count = error_count + 1
        error_msg = f"LLM error ({new_error_count}/{MAX_CONSECUTIVE_ERRORS}): {last_error[:200]}"
        logger.error(error_msg)
        fallback = AIMessage(content="I'm having trouble connecting to the AI model. Please try again in a moment.")
        return {
            "messages": [fallback],
            "iteration": iteration + 1,
            "error_count": new_error_count,
            "last_error": last_error[:200],
        }
    
    assistant_msg = response.choices[0].message
    
    # Convert to LangChain message format
    ai_message = AIMessage(
        content=assistant_msg.content or "",
        tool_calls=[
            {
                "id": tc.id,
                "name": tc.function.name,
                "args": json.loads(tc.function.arguments) if tc.function.arguments else {},
            }
            for tc in (assistant_msg.tool_calls or [])
        ] if assistant_msg.tool_calls else []
    )
    
    # Emit tool calls
    if emit and assistant_msg.tool_calls:
        for tc in assistant_msg.tool_calls:
            try:
                emit("tool_call", {
                    "name": tc.function.name,
                    "args": json.loads(tc.function.arguments) if tc.function.arguments else {},
                    "iteration": iteration + 1
                })
            except Exception:
                pass
    
    return {
        "messages": [ai_message],
        "iteration": iteration + 1,
        "error_count": 0,  # Reset on success
        "last_error": None,
    }


def tool_executor(state: AgentState) -> AgentState:
    """Execute tool calls from the last AI message (parallel via ThreadPoolExecutor)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time as _time

    messages = state["messages"]
    emit = _current_emit
    tool_calls_total = state.get("tool_calls_total", 0)
    
    # Find the last AI message with tool calls
    last_ai_msg = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            last_ai_msg = msg
            break
    
    if not last_ai_msg:
        return {"messages": [], "tool_calls_total": tool_calls_total}
    
    def _execute_single(tc):
        """Execute a single tool call (runs in thread)"""
        tool_name = tc["name"]
        tool_args = tc["args"]
        tool_id = tc["id"]
        tool = registry.get(tool_name)
        
        # Permission gate — only "destructive" tools require explicit user approval
        if tool and tool.permission == "destructive":
            # Emit confirmation_required event and wait for user response
            approval_event = threading.Event()
            _approval_events[tool_id] = approval_event
            
            if emit:
                try:
                    emit("confirmation_required", {
                        "tool_call_id": tool_id,
                        "name": tool_name,
                        "args": tool_args,
                        "permission": tool.permission,
                    })
                except Exception:
                    pass
            
            logger.info(f"Approval gate: waiting for user confirmation of '{tool_name}'")
            approved = approval_event.wait(timeout=120)  # 2 minute timeout
            
            # Clean up
            _approval_events.pop(tool_id, None)
            result_approved = _approval_results.pop(tool_id, False)
            
            if not approved or not result_approved:
                result = f"Action '{tool_name}' was declined or timed out."
                logger.info(f"Approval gate: user denied or timed out for '{tool_name}'")
                return ToolMessage(content=result, tool_call_id=tool_id)
            
            logger.info(f"Approval gate: user approved '{tool_name}'")
        
        # Execute tool
        start = _time.time()
        try:
            result = registry.execute(tool_name, tool_args)
        except Exception as e:
            result = f"Error executing {tool_name}: {str(e)}"
            logger.error_with_context(f"Tool {tool_name} failed", e)
        
        duration = (_time.time() - start) * 1000
        logger.tool_call(tool_name, tool_args, result)
        
        # Emit result
        if emit:
            try:
                emit("tool_result", {
                    "name": tool_name,
                    "result": str(result)[:500],
                    "duration_ms": round(duration),
                    "success": not str(result).startswith("Error")
                })
            except Exception:
                pass
        
        return ToolMessage(content=str(result)[:2000], tool_call_id=tool_id)
    
    # Execute all tools in parallel
    tool_messages = []
    with ThreadPoolExecutor(max_workers=min(len(last_ai_msg.tool_calls), 5)) as executor:
        futures = {executor.submit(_execute_single, tc): tc for tc in last_ai_msg.tool_calls}
        for future in as_completed(futures):
            try:
                tool_messages.append(future.result())
            except Exception as e:
                tc = futures[future]
                tool_messages.append(ToolMessage(
                    content=f"Error: {str(e)}",
                    tool_call_id=tc["id"]
                ))
    
    return {
        "messages": tool_messages,
        "tool_calls_total": tool_calls_total + len(last_ai_msg.tool_calls),
    }


def should_continue(state: AgentState) -> str:
    """Determine if we should continue the agent loop"""
    messages = state["messages"]
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 10)
    
    # Check iteration limit
    if iteration >= max_iterations:
        logger.debug(f"Agent reached max iterations ({max_iterations})")
        return "end"
    
    # Find the last AI message
    last_ai_msg = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            last_ai_msg = msg
            break
    
    # If no tool calls, we're done
    if not last_ai_msg or not last_ai_msg.tool_calls:
        return "end"
    
    # Continue with tool execution
    return "tools"


def create_agent_graph():
    """Create the LangGraph state machine for the agent with checkpointing"""
    # Define the graph
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("llm", llm_call)
    graph.add_node("tools", tool_executor)
    
    # Set entry point
    graph.set_entry_point("llm")
    
    # Add conditional edges
    graph.add_conditional_edges(
        "llm",
        should_continue,
        {
            "tools": "tools",
            "end": END
        }
    )
    
    # Tools always go back to LLM
    graph.add_edge("tools", "llm")
    
    # Try Turso cloud first, then local SQLite, then in-memory
    checkpointer = None
    
    # 1. Try local SQLite
    if checkpointer is None:
        try:
            import sqlite3
            from langgraph.checkpoint.sqlite import SqliteSaver
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            conn = sqlite3.connect(str(data_dir / "checkpoints.db"), check_same_thread=False)
            checkpointer = SqliteSaver(conn)
            logger.info("Using local SQLite checkpointer for persistence")
        except Exception:
            checkpointer = MemorySaver()
            logger.info("Using MemorySaver (in-memory) checkpointer")
    
    return graph.compile(checkpointer=checkpointer)


# Singleton graph instance
agent_graph = create_agent_graph()


def run_agent(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    emit=None,
    max_iterations: int = 10,
    thread_id: str = "default"
) -> str:
    """Run the agent graph and return the final response
    
    This is the main entry point that replaces the manual loop in core.py.
    
    Args:
        messages: List of message dicts (system, user, etc.)
        tools: List of tool schemas for the LLM
        emit: Optional callback for streaming events
        max_iterations: Maximum number of tool-calling iterations
        thread_id: Thread ID for checkpoint persistence
        
    Returns:
        The final text response from the agent
    """
    # Convert message dicts to LangChain messages
    lc_messages = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        
        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        elif role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            # Preserve tool_calls if present
            tool_calls = msg.get("tool_calls", [])
            lc_messages.append(AIMessage(
                content=content,
                tool_calls=tool_calls
            ))
        elif role == "tool":
            lc_messages.append(ToolMessage(
                content=content,
                tool_call_id=msg.get("tool_call_id", "")
            ))
    
    # Run the graph with checkpoint config
    global _current_emit
    _current_emit = emit
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
        result = agent_graph.invoke(initial_state, config=config)
        _current_emit = None
        
        # Extract final response
        final_messages = result["messages"]
        for msg in reversed(final_messages):
            if isinstance(msg, AIMessage) and msg.content:
                return msg.content
        
        return "Done."
        
    except Exception as e:
        _current_emit = None
        logger.error(f"Agent graph failed: {e}")
        raise


def resolve_approval(tool_call_id: str, approved: bool):
    """Resolve a pending approval request from the frontend
    
    Called by the Socket.IO handler when the user clicks Allow/Deny.
    """
    event = _approval_events.get(tool_call_id)
    if event:
        _approval_results[tool_call_id] = approved
        event.set()
        logger.info(f"Approval resolved: tool_call_id={tool_call_id}, approved={approved}")
    else:
        logger.warning(f"Approval resolved for unknown tool_call_id: {tool_call_id}")
