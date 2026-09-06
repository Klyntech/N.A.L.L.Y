"""
Wave 1 — OpenCode adapter (thin, frozen-config compliant).

Provider: opencode/hy3-free
Model: muse-spark-1.2-contributor-free (primary) via OPENCODE_API_KEY
Flow: frozen config -> LLM request -> trajectory -> Wave1Runner -> suite scorer

Never mutates: 80 worlds, scorers, config.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

from tests.eval.wave1.config import FROZEN, DEFAULT_TEMPERATURE

PROVIDER_ID = "opencode/hy3-free"
MODEL = "muse-spark-1.2-contributor-free"
BASE_URL = "https://opencode.ai/zen/v1"

SIMWORLD_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "search_contacts": {"query": {"type": "string"}},
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
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": props, "required": list(props.keys())},
            },
        })
    return tools


def _get_client():
    api_key = os.getenv("OPENCODE_API_KEY", "").split(",")[0].strip()
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
    lines = [f"Task: {getattr(task, 'initial_user_message', '')}", f"Available tools: {', '.join(getattr(task, 'available_tools', []))}"]
    init = getattr(task, "initial_state", {})
    if init:
        summary = {k: (len(v) if isinstance(v, list) else len(v) if isinstance(v, dict) else v) for k, v in init.items()}
        lines.append(f"Initial state summary: {json.dumps(summary)[:800]}")
    if getattr(task, "type", None):
        lines.append(f"Task type: {task.type}")
        if task.type == "verification":
            lines.append(f"Candidate plan: {json.dumps(getattr(task, 'candidate_plan', []))[:800]}")
    return "\n".join(lines)


def _parse_plan_json(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "plan" in data:
            return data["plan"]
    except Exception:
        pass
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
    if getattr(task, "type", None) in ("generation", "optimal", "replan", "reuse", "verification", "execution"):
        return _adapter_p_world(task, temperature)
    return _adapter_simworld(task, temperature, max_calls or FROZEN.budget["MAX_TOOL_CALLS"], getattr(task, "seed", 0))


def _adapter_simworld(task: Any, temperature: float, max_calls: int, seed: int) -> List[Dict[str, Any]]:
    client = _get_client()
    if client is None:
        return []
    world_mod = __import__("tests.eval.suite_t.world", fromlist=["SimWorld"])
    SimWorld = world_mod.SimWorld
    world = SimWorld(getattr(task, "initial_state", {}))
    available = list(getattr(task, "available_tools", []))
    tools = _tool_defs(available, world="sim")
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": "You are a tool-using assistant. Call tools to achieve the task. When done, call end_conversation with the result."},
        {"role": "user", "content": _initial_context(task)},
    ]
    trajectory: List[Dict[str, Any]] = []
    for _ in range(min(max_calls, 8)):
        try:
            # opencode hy3-free / muse-spark both support chat.completions; muse-spark prefers responses API
            # but chat path works via NallyLLM fallback — here we use chat directly.
            # For muse-spark family, use responses-style via client if needed: try chat first.
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                temperature=temperature,
                max_tokens=1024,
            )
        except Exception as e:
            # Muse Spark may require responses API; try via nally LLM helper as fallback
            try:
                from nally.agent.llm import llm as nally_llm
                # Use the shared NallyLLM which already handles muse-spark responses mapping
                r = nally_llm.chat(messages=messages, tools=tools, temperature=temperature)
                # Convert to OpenAI-like shape for uniform handling
                class _Resp: pass
                msg = r.choices[0].message
                tc = getattr(msg, "tool_calls", None)
                # Re-inject into trajectory handling below by mocking resp
                resp = type("R", (), {"choices": [type("C", (), {"message": msg})()]})()
            except Exception as e2:
                trajectory.append({"role": "agent", "name": "end_conversation", "args": {"result": f"provider_error: {str(e)[:180]}"}})
                break
        msg = resp.choices[0].message
        content = msg.content or ""
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            if content.strip():
                trajectory.append({"role": "agent", "name": "end_conversation", "args": {"result": _truncate(content, 500)}})
            break
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except Exception:
                args = {}
            trajectory.append({"role": "agent", "name": name, "args": args})
            if name == "end_conversation":
                break
            ok, out = world.apply_tool(name, args)
            messages.append({"role": "assistant", "content": content, "tool_calls": [{"id": tc.id, "type": "function", "function": {"name": name, "arguments": tc.function.arguments or "{}"}}]})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": _truncate(out, 2000)})
        if any(t.get("name") == "end_conversation" for t in trajectory):
            break
        if tool_calls and content:
            messages.append({"role": "assistant", "content": content})
    return trajectory


def _adapter_p_world(task: Any, temperature: float) -> List[Dict[str, Any]]:
    client = _get_client()
    # Try direct OpenAI client first; if that fails (muse-spark needs responses), fall back to NallyLLM
    def _call(messages):
        if client is not None:
            try:
                r = client.chat.completions.create(model=MODEL, messages=messages, temperature=temperature, max_tokens=1024)
                return r.choices[0].message.content or ""
            except Exception:
                pass
        try:
            from nally.agent.llm import llm as nally_llm
            return nally_llm.chat(messages=messages, temperature=temperature).choices[0].message.content or ""
        except Exception:
            return ""

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
    text = _call(messages)
    if not text:
        return []
    if getattr(task, "type", None) in ("generation", "optimal", "replan", "reuse"):
        plan = _parse_plan_json(text)
        norm = []
        for step in plan:
            if isinstance(step, dict) and "action" in step:
                norm.append({"action": step["action"], "args": step.get("args", {})})
            elif isinstance(step, dict) and "name" in step:
                norm.append({"action": step["name"], "args": step.get("args", {})})
        return norm
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
