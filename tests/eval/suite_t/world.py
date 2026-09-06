"""Simulated world for Suite T — test-side only, fully deterministic.

A tiny stateful tool environment (files / settings / contacts / messages /
docs) with implicit dependencies between tools, e.g. send_message fails
while cellular is off, enabling cellular fails while battery saver is on.

No production code is imported or touched. All tool output is truncated
test-side (5k chars) so a chatty tool can never OOM the harness worker
(see docs/research/02-experiment-design.md section 0.5).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Tuple

OUTPUT_CAP = 5000  # test-side truncation; independent of NALLY_MAX_TOOL_OUTPUT

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}

_MULTIPLIER = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def _cap(text: str) -> str:
    if len(text) > OUTPUT_CAP:
        return text[:OUTPUT_CAP] + f"...[truncated {len(text) - OUTPUT_CAP} chars]"
    return text


class SimWorld:
    """In-memory world snapshot + deterministic simulated tools."""

    def __init__(self, initial_state: Dict[str, Any]):
        self.state: Dict[str, Any] = copy.deepcopy(initial_state)
        self.state.setdefault("files", {})
        self.state.setdefault("settings", {"cellular": True, "battery_saver": False})
        self.state.setdefault("contacts", [])
        self.state.setdefault("messages", [])
        self.state.setdefault("docs", [])
        self.state.setdefault("today", "2026-09-02")
        self.state.setdefault("reported", None)

    # -- snapshots ------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        return copy.deepcopy(self.state)

    def snapshot_hash(self) -> str:
        blob = json.dumps(self.state, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    # -- dispatch --------------------------------------------------------
    def apply_tool(self, name: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            return False, f"UnknownTool: {name}"
        try:
            ok, result = handler(args or {})
        except Exception as e:  # simulated tools never raise out
            return False, f"ToolError({name}): {e}"
        return ok, _cap(str(result))

    # -- simulated tools --------------------------------------------------
    def tool_search_contacts(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        query = str(args.get("query", "")).lower()
        hits = [c for c in self.state["contacts"] if query in c["name"].lower()]
        return True, json.dumps(hits)

    def tool_send_message(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        if not self.state["settings"].get("cellular", True):
            return False, "ConnectionError: cellular service is off"
        phone, text = args.get("phone"), args.get("text", "")
        if not phone:
            return False, "ValueError: 'phone' argument is required"
        self.state["messages"].append({"phone": phone, "text": text})
        return True, json.dumps({"sent": True, "phone": phone})

    def tool_set_cellular(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        status = bool(args.get("status", True))
        if status and self.state["settings"].get("battery_saver", False):
            return False, "StateError: cannot enable cellular while battery saver is on"
        self.state["settings"]["cellular"] = status
        return True, json.dumps({"cellular": status})

    def tool_set_battery_saver(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        status = bool(args.get("status", False))
        self.state["settings"]["battery_saver"] = status
        return True, json.dumps({"battery_saver": status})

    def tool_read_file(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        path = args.get("path", "")
        if path not in self.state["files"]:
            return False, f"FileNotFoundError: {path}"
        return True, self.state["files"][path]

    def tool_write_file(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        path = args.get("path", "")
        if not path:
            return False, "ValueError: 'path' argument is required"
        self.state["files"][path] = str(args.get("content", ""))
        # Track dirs implicitly for suite_a/p shell checks
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        if parent:
            self.state.setdefault("dirs", [])
            cur = ""
            for part in parent.split("/"):
                cur = f"{cur}/{part}" if cur else part
                if cur not in self.state["dirs"]:
                    self.state["dirs"].append(cur)
        return True, json.dumps({"written": path})

    def tool_create_dir(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        path = args.get("path", "")
        if not path:
            return False, "ValueError: 'path' is required"
        self.state.setdefault("dirs", [])
        if path in self.state["dirs"] or path in self.state["files"]:
            return False, f"FileExistsError: {path} already exists"
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        if parent and parent not in self.state["dirs"]:
            return False, f"FileNotFoundError: parent {parent} does not exist"
        self.state["dirs"].append(path)
        return True, json.dumps({"created": path})

    def tool_move_file(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        src, dst = args.get("src", ""), args.get("dst", "")
        if src not in self.state["files"]:
            return False, f"FileNotFoundError: {src}"
        parent = dst.rsplit("/", 1)[0] if "/" in dst else ""
        if parent and parent not in self.state.get("dirs", []):
            return False, f"FileNotFoundError: dest parent {parent} missing"
        self.state["files"][dst] = self.state["files"].pop(src)
        return True, json.dumps({"moved": f"{src} -> {dst}"})

    def tool_delete_file(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        path = args.get("path", "")
        if path not in self.state["files"]:
            return False, f"FileNotFoundError: {path}"
        del self.state["files"][path]
        return True, json.dumps({"deleted": path})

    def tool_search_docs(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        query = str(args.get("query", "")).lower()
        tokens = [t for t in re.findall(r"[a-z0-9]+", query) if len(t) > 2]
        scored = []
        for doc in self.state["docs"]:
            hay = (doc.get("title", "") + " " + doc.get("snippet", "")).lower()
            score = sum(hay.count(t) for t in tokens)
            scored.append((score, doc))
        scored.sort(key=lambda s: s[0], reverse=True)
        top = [{"id": d["id"], "snippet": d["snippet"]} for s, d in scored[:3]]
        return True, json.dumps(top)

    def tool_fetch_doc(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        doc_id = args.get("doc_id", "")
        for doc in self.state["docs"]:
            if doc.get("id") == doc_id:
                return True, doc.get("content", "")
        return False, f"DocNotFound: {doc_id}"

    def tool_calc(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        expr = str(args.get("expression", ""))
        if not re.fullmatch(r"[\d\s+\-*/().%]+", expr):
            return False, "ValueError: expression must be arithmetic only"
        try:
            value = eval(expr, {"__builtins__": {}}, {})  # noqa: S307 (sandboxed grammar)
        except Exception as e:
            return False, f"CalcError: {e}"
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return True, json.dumps({"result": value})

    def tool_calendar_lookup(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        return True, json.dumps({"today": self.state["today"]})

    def tool_canonicalize(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        value, kind = str(args.get("value", "")), args.get("kind", "")
        if kind == "number":
            return True, json.dumps({"canonical": self._canon_number(value)})
        if kind == "currency":
            for symbol, code in _CURRENCY.items():
                if symbol in value:
                    return True, json.dumps({"canonical": code})
            return False, f"CanonicalizeError: unknown currency in {value!r}"
        if kind == "date":
            resolved = self._canon_date(value)
            if resolved is None:
                return False, f"CanonicalizeError: cannot resolve date {value!r}"
            return True, json.dumps({"canonical": resolved})
        if kind == "geo":
            return self._canon_geo(value)
        return False, f"CanonicalizeError: unknown kind {kind!r}"

    def tool_end_conversation(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        self.state["reported"] = args.get("result")
        return True, json.dumps({"reported": True})

    # -- canonicalization helpers ------------------------------------------
    @staticmethod
    def _canon_number(value: str) -> Any:
        text = value.strip().replace(",", "").lower()
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmb])?", text)
        if not match:
            raise ValueError(f"cannot canonicalize number {value!r}")
        number = float(match.group(1))
        if match.group(2):
            number *= _MULTIPLIER[match.group(2)]
        return int(number) if number.is_integer() else number

    def _canon_date(self, value: str) -> Any:
        text = value.strip().lower()
        today = date.fromisoformat(self.state["today"])
        if text in ("today",):
            return today.isoformat()
        if text in ("tomorrow",):
            return (today + timedelta(days=1)).isoformat()
        match = re.fullmatch(r"(?:this|next)\s+(\w+)", text)
        if match and match.group(1) in _WEEKDAYS:
            target = _WEEKDAYS[match.group(1)]
            delta = (target - today.weekday()) % 7
            if delta == 0:
                delta = 7
            return (today + timedelta(days=delta)).isoformat()
        iso = re.fullmatch(r"\d{4}-\d{2}-\d{2}", text)
        if iso:
            return text
        return None

    def _canon_geo(self, value: str) -> Tuple[bool, str]:
        for doc in self.state["docs"]:
            if doc.get("kind") == "geo" and value.lower() in doc.get("title", "").lower():
                return True, doc.get("content", "")
        return False, f"CanonicalizeError: no geo entry for {value!r}; lookup required"
