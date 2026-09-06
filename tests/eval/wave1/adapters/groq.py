"""
Wave 1 — Groq adapter (thin, frozen-config compliant).

Provider: groq/llama-3.3
Model: llama-3.3-70b-versatile (via GROQ_API_KEY)
Flow: frozen config -> LLM request -> trajectory -> Wave1Runner -> suite scorer

Never mutates: 80 worlds, scorers, config.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List

from tests.eval.wave1.config import FROZEN, DEFAULT_TEMPERATURE

PROVIDER_ID = "groq/llama-3.3"
MODEL = "llama-3.3-70b-versatile"
BASE_URL = "https://api.groq.com/openai/v1"

# Tool schemas for SimWorld (suite_t/a/c) — keep in sync with tests/eval/suite_t/world.py
SIMWORLD_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "search_contacts": {"query": {"type": "string", "description": "substring to search"}},
    "send_message": {"phone": {"type": "string"}, "text": {"type": "string"}},
    "set_cellular": {"status": {"type": "boolean"}},
    "set_battery_saver": {"status": {"type": "boolean"}},
    "read_file": {"path": {"type": "string"}},
    "write_file": {"path": {"type": "string"}, "content": {"type": "string"}},
    "search_docs": {"query": {"type": "string"}},
    "fetch_doc": {"doc_id": {"type": "string"}},
    "calc": {"expression": {"type": "string"}},
    "calendar_lookup": {},
    "canonicalize": {"value": {"type": "string"}, "kind": {"type": "string", "enum": ["number", "currency", "date", "geo"]}},
    "end_conversation": {"result": {"type": "string"}},
    "create_dir": {"path": {"type": "string"}},
    "move_file": {"src": {"type": "string"}, "dst": {"type": "string"}},
    "delete_file": {"path": {"type": "string"}},
}

P_WORLD_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "create_dir": {"path": {"type": "string"}},
    "write_file": {"path": {"type": "string"}, "content": {"type": "string"}},
    "move_file": {"src": {"type": "string"}, "dst": {"type": "string"}},
    "delete_file": {"path": {"type": "string"}},
}


def _tool_defs(names: List[str], world: str = "sim") -> List[Dict[str, Any]]:
    src = P_WORLD_SCHEMAS if world == "p" else SIMWORLD_SCHEMAS
    tools = []
    for name in names:
        props = src.get(name, {})
        required = list(props.keys())
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": props, "required": required},
            },
        })
    return tools


def _get_client():
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key, base_url=BASE_URL, timeout=60.0, max_retries=1)
    except Exception:
        return None


def _truncate(s: str, n: int = 4000) -> str:
    return s[:n] + f"...[truncated {len(s)-n}]" if len(s) > n else s


def _initial_context(task: Any) -> str:
    """Minimal task context — never injects scorer or gold."""
    lines = [f"Task: {getattr(task, 'initial_user_message', '')}", f"Available tools: {', '.join(getattr(task, 'available_tools', []))}"]
    init = getattr(task, "initial_state", {})
    if init:
        # Show only a summary to avoid stuffing the prompt
        summary = {k: (len(v) if isinstance(v, list) else len(v) if isinstance(v, dict) else v) for k, v in init.items()}
        lines.append(f"Initial state summary: {json.dumps(summary)[:800]}")
    # suite_p specific
    if getattr(task, "type", None):
        lines.append(f"Task type: {task.type}")
        if task.type == "verification":
            lines.append(f"Candidate plan: {json.dumps(getattr(task, 'candidate_plan', []))[:800]}")
    return "\n".join(lines)


def _parse_plan_json(text: str) -> List[Dict[str, Any]]:
    """Extract first JSON array/object containing a plan."""
    if not text:
        return []
    # try direct json
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "plan" in data:
            return data["plan"]
    except Exception:
        pass
    # extract json block
    m = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", text)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "plan" in data:
                return data["plan"]
        except Exception:
            pass
    return []


def adapter(task: Any, temperature: float = DEFAULT_TEMPERATURE, max_calls: int = None) -> List[Dict[str, Any]]:
    """
    Thin Groq adapter: task -> trajectory events.
    Respects FROZEN budget and temperature; provider is fixed to Groq.
    Returns [] on missing API key (caller treats as 0-score, never crashes harness).
    """
    from tests.eval.suite_t.world import SimWorld

    max_calls = max_calls or FROZEN.budget["MAX_TOOL_CALLS"]
    seed = getattr(task, "seed", 0)
    # suite_p branch — single LLM call for plan/verdict
    if getattr(task, "type", None) in ("generation", "optimal", "replan", "reuse", "verification", "execution"):
        return _adapter_p_world(task, temperature)
    # suite_t/a/c — ReAct loop with SimWorld
    return _adapter_simworld(task, temperature, max_calls, seed)


def _adapter_simworld(task: Any, temperature: float, max_calls: int, seed: int) -> List[Dict[str, Any]]:
    client = _get_client()
    if client is None:
        return []  # missing key -> 0-score, harness records diagnostics
    from tests.eval.suite_t.world import SimWorld

    world = SimWorld(getattr(task, "initial_state", {}))
    available = list(getattr(task, "available_tools", []))
    tools = _tool_defs(available, world="sim")
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": "You are a tool-using assistant. Call tools to achieve the task. When done, call end_conversation with the result."},
        {"role": "user", "content": _initial_context(task)},
    ]
    trajectory: List[Dict[str, Any]] = []
    for _ in range(min(max_calls, 8)):  # cap inner loop for Wave 1 smoke (full budget is 50, but smoke uses 8)
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                temperature=temperature,
                max_tokens=1024,
            )
        except Exception as e:
            # provider error -> stop, return what we have (harness scores partial)
            trajectory.append({"role": "agent", "name": "end_conversation", "args": {"result": f"provider_error: {str(e)[:200]}"}})
            break
        msg = resp.choices[0].message
        content = msg.content or ""
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            # No tool call: treat content as end_conversation if present
            if content.strip():
                trajectory.append({"role": "agent", "name": "end_conversation", "args": {"result": _truncate(content, 500)}})
            break
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except Exception:
                args = {}
            # record trajectory
            trajectory.append({"role": "agent", "name": name, "args": args})
            if name == "end_conversation":
                break
            # execute in SimWorld and feed back
            ok, out = world.apply_tool(name, args)
            messages.append({"role": "assistant", "content": content, "tool_calls": [{"id": tc.id, "type": "function", "function": {"name": name, "arguments": tc.function.arguments or "{}"}}]})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": _truncate(out, 2000)})
        # check if we already ended
        if any(t.get("name") == "end_conversation" for t in trajectory):
            break
        # append assistant content for next turn if no tool call content already
        if tool_calls and content:
            messages.append({"role": "assistant", "content": content})
    return trajectory


def _adapter_p_world(task: Any, temperature: float) -> List[Dict[str, Any]]:
    client = _get_client()
    if client is None:
        return []
    # main prompt for P world — ask for JSON
    if getattr(task, "type", None) in ("generation", "optimal", "replan", "reuse"):
        prompt = _initial_context(task) + "\nReturn a JSON object with key 'plan' as a list of {\"action\":...,\"args\":{...}} steps. Only use actions: create_dir, write_file, move_file, delete_file."
    elif getattr(task, "type", None) == "verification":
        prompt = _initial_context(task) + "\nReturn JSON {\"executable\": bool, \"goal_reached\": bool, \"first_failure_index\": int or null}."
    elif getattr(task, "type", None) == "execution":
        prompt = _initial_context(task) + f"\nActions: {json.dumps(getattr(task, 'start_and_actions', {}).get('actions', []))}\nReturn JSON predicted_state like {{\"dirs\": [...], \"files\": {{...}}}}."
    else:
        prompt = _initial_context(task)
    messages = [
        {"role": "system", "content": "You are a file-system planner. Return ONLY valid JSON, no prose."},
        {"role": "user", "content": prompt},
    ]
    try:
        resp = client.chat.completions.create(model=MODEL, messages=messages, temperature=temperature, max_tokens=1024)
        text = resp.choices[0].message.content or ""
    except Exception as e:
        return []
    # parse according to task type
    if getattr(task, "type", None) in ("generation", "optimal", "replan", "reuse"):
        plan = _parse_plan_json(text)
        # Normalize to action/args shape for Wave1Runner
        norm = []
        for step in plan:
            if isinstance(step, dict) and "action" in step:
                norm.append({"action": step["action"], "args": step.get("args", {})})
            elif isinstance(step, dict) and "name" in step:
                norm.append({"action": step["name"], "args": step.get("args", {})})
        return norm if norm else _parse_plan_json(text)
    elif getattr(task, "type", None) == "verification":
        try:
            data = json.loads(text)
            if "executable" in data:
                return [data]
        except Exception:
            pass
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return [json.loads(m.group(0))]
            except Exception:
                pass
        return []
    elif getattr(task, "type", None) == "execution":
        try:
            data = json.loads(text)
            if "dirs" in data or "files" in data:
                return [{"predicted_state": data}]
            if "predicted_state" in data:
                return [{"predicted_state": data["predicted_state"]}]
        except Exception:
            pass
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                data = json.loads(m.group(0))
                return [{"predicted_state": data}]
            except Exception:
                pass
        return []
    return []
