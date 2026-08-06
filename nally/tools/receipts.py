"""Nally Receipt Store — HMAC-signed tool execution receipts.

Every tool call produces a receipt that proves what actually happened.
The LLM cannot forge these. Used by the verifier to catch hallucinated claims.

Design:
  - Receipt = {id, timestamp, tool, args, result, success, duration_ms, hash, hmac}
  - Receipts stored in JSONL (one per line, append-only)
  - HMAC-SHA256 signs the receipt content (tamper-evident)
  - receipts keyed by tool_call_id for fast lookup
"""

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class Receipt:
    """A single tool execution receipt."""

    __slots__ = ("args", "duration_ms", "hash", "hmac", "id", "result", "success", "timestamp", "tool", "tool_call_id")

    def __init__(
        self,
        tool_call_id: str,
        tool: str,
        args: Dict[str, Any],
        result: str,
        success: bool,
        duration_ms: float,
    ):
        self.id = secrets.token_hex(16)
        self.timestamp = time.time()
        self.tool_call_id = tool_call_id
        self.tool = tool
        self.args = args
        self.result = result
        self.success = success
        self.duration_ms = duration_ms
        self.hash = ""
        self.hmac = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "tool_call_id": self.tool_call_id,
            "tool": self.tool,
            "args": self.args,
            "result": self.result,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "hash": self.hash,
            "hmac": self.hmac,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Receipt":
        r = cls.__new__(cls)
        for k in cls.__slots__:
            setattr(r, k, data.get(k, ""))
        return r


class ReceiptStore:
    """Append-only receipt store with HMAC signing."""

    def __init__(self, store_path: Optional[Path] = None, secret_key: Optional[str] = None):
        self.store_path = store_path or Path("data/receipts.jsonl")
        self._key_path = self.store_path.parent / ".receipt_key"
        self._secret_key = self._load_or_create_key(secret_key)
        self._by_tool_call_id: Dict[str, Receipt] = {}
        self._load_existing()

    def _load_or_create_key(self, provided_key: Optional[str]) -> bytes:
        """Load existing key or create persistent one."""
        if provided_key:
            return provided_key.encode()
        env_key = os.environ.get("NALLY_RECEIPT_KEY")
        if env_key:
            return env_key.encode()
        if self._key_path.exists():
            try:
                return self._key_path.read_text().strip().encode()
            except Exception:
                pass
        key = secrets.token_hex(32)
        try:
            self._key_path.parent.mkdir(parents=True, exist_ok=True)
            self._key_path.write_text(key)
        except Exception:
            pass
        return key.encode()

    def _load_existing(self):
        """Load receipts from disk on startup."""
        if not self.store_path.exists():
            return
        try:
            with open(self.store_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        r = Receipt.from_dict(data)
                        self._by_tool_call_id[r.tool_call_id] = r
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception:
            pass

    def _compute_hash(self, receipt: Receipt) -> str:
        """SHA-256 of canonical receipt content (excludes hash and hmac fields)."""
        content = json.dumps(
            {
                "id": receipt.id,
                "timestamp": receipt.timestamp,
                "tool_call_id": receipt.tool_call_id,
                "tool": receipt.tool,
                "args": receipt.args,
                "result": receipt.result,
                "success": receipt.success,
                "duration_ms": receipt.duration_ms,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def _compute_hmac(self, receipt: Receipt) -> str:
        """HMAC-SHA256 of the receipt hash (tamper-evident signature)."""
        return hmac.new(self._secret_key, receipt.hash.encode(), hashlib.sha256).hexdigest()

    def record(
        self,
        tool_call_id: str,
        tool: str,
        args: Dict[str, Any],
        result: str,
        success: bool,
        duration_ms: float,
    ) -> Receipt:
        """Record a tool execution and return the signed receipt."""
        receipt = Receipt(tool_call_id, tool, args, result, success, duration_ms)
        receipt.hash = self._compute_hash(receipt)
        receipt.hmac = self._compute_hmac(receipt)

        # In-memory index
        self._by_tool_call_id[tool_call_id] = receipt

        # Append to disk
        try:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.store_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(receipt.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            import logging
            logging.getLogger("nally.receipts").error(f"Failed to persist receipt {receipt.id}: {e}")

        return receipt

    def get(self, tool_call_id: str) -> Optional[Receipt]:
        """Get receipt by tool_call_id."""
        return self._by_tool_call_id.get(tool_call_id)

    def get_by_tool(self, tool_name: str, limit: int = 50) -> List[Receipt]:
        """Get recent receipts for a specific tool."""
        results = [r for r in self._by_tool_call_id.values() if r.tool == tool_name]
        results.sort(key=lambda r: r.timestamp, reverse=True)
        return results[:limit]

    def get_recent(self, limit: int = 50) -> List[Receipt]:
        """Get most recent receipts across all tools."""
        results = list(self._by_tool_call_id.values())
        results.sort(key=lambda r: r.timestamp, reverse=True)
        return results[:limit]

    def verify(self, receipt: Receipt) -> bool:
        """Verify receipt integrity — hash matches and HMAC is valid."""
        expected_hash = self._compute_hash(receipt)
        if not hmac.compare_digest(receipt.hash, expected_hash):
            return False
        expected_hmac = self._compute_hmac(receipt)
        return hmac.compare_digest(receipt.hmac, expected_hmac)

    def format_for_context(self, receipts: List[Receipt]) -> str:
        """Format receipts as a human-readable summary for LLM context injection."""
        if not receipts:
            return ""
        lines = ["[Tool Execution Receipts — verified ground truth]"]
        for r in receipts:
            status = "OK" if r.success else "FAILED"
            result_preview = r.result[:120] if r.result else "(no output)"
            lines.append(f"  [{status}] {r.tool}(id={r.tool_call_id[:12]}): {result_preview}")
        return "\n".join(lines)


# Singleton
receipt_store = ReceiptStore()
