"""Nally Receipt Store — HMAC-signed tool execution receipts.

Every tool call produces a receipt that proves what actually happened.
The LLM cannot forge these. Used by the verifier to catch hallucinated claims.

Design:
  - Receipt = {id, timestamp, tool, args, result, success, duration_ms, hash, hmac}
  - Receipts stored in JSONL (one per line, append-only)
  - HMAC-SHA256 signs the receipt content (tamper-evident)
  - receipts keyed by tool_call_id for fast lookup
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nally.receipts")


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64url_decode(s: str) -> bytes:
    # Pad to multiple of 4
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


class Receipt:
    """A single tool execution receipt — now with JCS + Ed25519 + chain (lesson 18)."""

    __slots__ = (
        "args",
        "duration_ms",
        "hash",
        "hmac",
        "id",
        "prev_hash",
        "public_key",
        "result",
        "signature",
        "success",
        "timestamp",
        "tool",
        "tool_call_id",
    )

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
        self.prev_hash = ""
        self.signature = ""
        self.public_key = ""

    def to_dict(self) -> Dict[str, Any]:
        d = {
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
        # Only include chain/signature fields when present (keeps old JSONL compact)
        if getattr(self, "prev_hash", ""):
            d["prev_hash"] = self.prev_hash
        if getattr(self, "signature", ""):
            d["signature"] = self.signature
        if getattr(self, "public_key", ""):
            d["public_key"] = self.public_key
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Receipt":
        r = cls.__new__(cls)
        for k in cls.__slots__:
            setattr(r, k, data.get(k, ""))
        return r


class ReceiptStore:
    """Append-only receipt store with HMAC signing and rotation."""

    MAX_STORE_SIZE = 10 * 1024 * 1024  # 10MB before rotation
    MAX_ROTATED_FILES = 5  # Keep up to 5 rotated files

    def __init__(self, store_path: Optional[Path] = None, secret_key: Optional[str] = None):
        if store_path is None:
            from ..config import DATA_DIR

            store_path = DATA_DIR / "receipts.jsonl"
        self.store_path = store_path
        self._key_path = self.store_path.parent / ".receipt_key"
        self._secret_key = self._load_or_create_key(secret_key)
        # Ed25519 keypair for asymmetric receipts (lesson 18) — separate from HMAC
        self._ed_priv_path = self.store_path.parent / ".receipt_ed25519_priv"
        self._ed_pub_path = self.store_path.parent / ".receipt_ed25519_pub"
        self._ed_priv = None  # Ed25519PrivateKey or None
        self._ed_pub_b64 = ""  # b64url public key for receipts
        self._last_hash = ""  # chain head for prev_hash linking
        self._init_ed_keys()
        self._by_tool_call_id: Dict[str, Receipt] = {}
        # Idempotency cache: (session_id, task_id) -> result string
        self._idempotent: Dict[str, str] = {}
        # Guards the in-memory dicts, which are shared across tool-executor
        # worker threads (record/get_recent/get_idempotent).
        self._lock = threading.Lock()
        self._load_existing()
        # After loading, set _last_hash to most recent receipt's hash for chaining
        try:
            if self._by_tool_call_id:
                latest = max(self._by_tool_call_id.values(), key=lambda r: r.timestamp)
                self._last_hash = latest.hash or ""
        except Exception:
            pass

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
            except Exception as e:
                logger.warning(f"Failed to read HMAC key from {self._key_path}: {e}")
        key = secrets.token_hex(32)
        try:
            self._key_path.parent.mkdir(parents=True, exist_ok=True)
            self._key_path.write_text(key)
            try:
                os.chmod(self._key_path, 0o600)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Failed to persist HMAC key to {self._key_path}: {e}")
        return key.encode()

    def _init_ed_keys(self):
        """Load or create Ed25519 keypair for asymmetric receipts. Graceful fallback if cryptography missing."""
        # Env override: NALLY_RECEIPT_ED_PRIV_B64 (b64url seed) or NALLY_RECEIPT_PRIV
        env_priv = os.getenv("NALLY_RECEIPT_ED_PRIV_B64", "") or os.getenv("NALLY_RECEIPT_ED_PRIV", "")
        if env_priv:
            try:
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

                seed = _b64url_decode(env_priv.strip()) if len(env_priv) > 44 else bytes.fromhex(env_priv.strip())
                # Ed25519 seed is 32 bytes
                if len(seed) == 32:
                    self._ed_priv = Ed25519PrivateKey.from_private_bytes(seed)
                    pub = self._ed_priv.public_key()
                    self._ed_pub_b64 = _b64url_encode(pub.public_bytes_raw())
                    return
            except Exception as e:
                logger.debug(f"Ed25519 env key load failed: {e}")

        # Try load from files
        if self._ed_priv_path.exists() and self._ed_pub_path.exists():
            try:
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

                priv_b64 = self._ed_priv_path.read_text().strip()
                pub_b64 = self._ed_pub_path.read_text().strip()
                priv_bytes = _b64url_decode(priv_b64)
                # priv file stores 32-byte seed b64url
                if len(priv_bytes) == 32:
                    self._ed_priv = Ed25519PrivateKey.from_private_bytes(priv_bytes)
                    self._ed_pub_b64 = pub_b64
                    return
                # Also support raw 32+64 file (legacy)
                if len(priv_bytes) >= 32:
                    self._ed_priv = Ed25519PrivateKey.from_private_bytes(priv_bytes[:32])
                    pub = self._ed_priv.public_key()
                    self._ed_pub_b64 = _b64url_encode(pub.public_bytes_raw())
                    return
            except Exception as e:
                logger.debug(f"Ed25519 file load failed: {e}")

        # Generate new pair
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

            priv = Ed25519PrivateKey.generate()
            pub = priv.public_key()
            priv_b64 = _b64url_encode(priv.private_bytes_raw())
            pub_b64 = _b64url_encode(pub.public_bytes_raw())
            try:
                self._ed_priv_path.parent.mkdir(parents=True, exist_ok=True)
                self._ed_priv_path.write_text(priv_b64)
                self._ed_pub_path.write_text(pub_b64)
                try:
                    os.chmod(self._ed_priv_path, 0o600)
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"Ed25519 persist failed: {e}")
            self._ed_priv = priv
            self._ed_pub_b64 = pub_b64
        except Exception as e:
            logger.debug(f"Ed25519 not available (cryptography missing?): {e}")
            self._ed_priv = None
            self._ed_pub_b64 = ""

    def _canonical_bytes(self, receipt: Receipt) -> bytes:
        """JCS-like canonical JSON for receipt (excluding hash/hmac/signature/pubkey)."""
        # Chain: include prev_hash when present so hash links chain
        payload: Dict[str, Any] = {
            "id": receipt.id,
            "timestamp": receipt.timestamp,
            "tool_call_id": receipt.tool_call_id,
            "tool": receipt.tool,
            "args": receipt.args,
            "result": receipt.result,
            "success": receipt.success,
            "duration_ms": receipt.duration_ms,
        }
        if getattr(receipt, "prev_hash", ""):
            payload["prev_hash"] = receipt.prev_hash
        # RFC8785: sort_keys + separators + ensure_ascii False + UTF-8
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def get_public_key(self) -> str:
        """Return b64url Ed25519 public key for /.well-known/nally-receipt-pubkey."""
        return self._ed_pub_b64

    def _rotate_if_needed(self):
        """Rotate receipt file if it exceeds MAX_STORE_SIZE."""
        if not self.store_path.exists():
            return
        if self.store_path.stat().st_size < self.MAX_STORE_SIZE:
            return

        # Remove oldest rotated file if at limit
        rotated = sorted(self.store_path.parent.glob("receipts.jsonl.*"))
        while len(rotated) >= self.MAX_ROTATED_FILES:
            try:
                rotated[0].unlink()
                rotated.pop(0)
            except Exception:
                break

        # Rotate current file
        next_num = len(rotated) + 1
        rotated_path = self.store_path.parent / f"receipts.jsonl.{next_num}"
        try:
            self.store_path.rename(rotated_path)
            logger.info(f"Rotated receipts to {rotated_path.name}")
        except Exception as e:
            logger.warning(f"Failed to rotate receipts: {e}")

    def _load_existing(self):
        """Load receipts from disk on startup (current + rotated files)."""
        # Load rotated files first (older data)
        rotated = sorted(self.store_path.parent.glob("receipts.jsonl.*"))
        for rotated_path in rotated:
            self._load_file(rotated_path)
        # Load current file last (newest data)
        self._load_file(self.store_path)

    def _load_file(self, path: Path):
        """Load receipts from a single JSONL file."""
        if not path.exists():
            return
        try:
            with open(path, encoding="utf-8") as f:
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
        except Exception as e:
            logger.warning(f"Failed to load receipts from {path}: {e}")

    def _compute_hash(self, receipt: Receipt) -> str:
        """SHA-256 of JCS canonical bytes (includes prev_hash for chaining)."""
        return hashlib.sha256(self._canonical_bytes(receipt)).hexdigest()

    def _compute_hmac(self, receipt: Receipt) -> str:
        """HMAC-SHA256 of the receipt hash (tamper-evident, backward compat)."""
        return hmac.new(self._secret_key, receipt.hash.encode(), hashlib.sha256).hexdigest()

    def _compute_signature(self, receipt: Receipt) -> str:
        """Ed25519 signature over canonical bytes, b64url. Empty if no private key."""
        if not self._ed_priv:
            return ""
        try:
            canon = self._canonical_bytes(receipt)
            sig = self._ed_priv.sign(canon)
            return _b64url_encode(sig)
        except Exception:
            return ""

    def record(
        self,
        tool_call_id: str,
        tool: str,
        args: Dict[str, Any],
        result: str,
        success: bool,
        duration_ms: float,
    ) -> Receipt:
        """Record a tool execution and return the signed receipt (dual HMAC + Ed25519 + chain)."""
        receipt = Receipt(tool_call_id, tool, args, result, success, duration_ms)
        # Chain: link to previous receipt's hash
        with self._lock:
            receipt.prev_hash = self._last_hash or ""
            receipt.hash = self._compute_hash(receipt)
            receipt.hmac = self._compute_hmac(receipt)
            receipt.signature = self._compute_signature(receipt)
            receipt.public_key = self._ed_pub_b64 if receipt.signature else ""
            self._by_tool_call_id[tool_call_id] = receipt
            self._last_hash = receipt.hash

        # In-memory index already updated under lock

        # Append to disk (with rotation check)
        try:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
            with open(self.store_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(receipt.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to persist receipt {receipt.id}: {e}")

        return receipt

    def get(self, tool_call_id: str) -> Optional[Receipt]:
        """Get receipt by tool_call_id."""
        with self._lock:
            return self._by_tool_call_id.get(tool_call_id)

    def get_by_tool(self, tool_name: str, limit: int = 50) -> List[Receipt]:
        """Get recent receipts for a specific tool."""
        with self._lock:
            results = [r for r in self._by_tool_call_id.values() if r.tool == tool_name]
        results.sort(key=lambda r: r.timestamp, reverse=True)
        return results[:limit]

    def get_recent(self, limit: int = 50) -> List[Receipt]:
        """Get most recent receipts across all tools."""
        with self._lock:
            results = list(self._by_tool_call_id.values())
        results.sort(key=lambda r: r.timestamp, reverse=True)
        return results[:limit]

    def verify(self, receipt: Receipt) -> bool:
        """Verify receipt integrity — JCS hash + HMAC + optional Ed25519."""
        expected_hash = self._compute_hash(receipt)
        if not hmac.compare_digest(receipt.hash or "", expected_hash):
            return False
        expected_hmac = self._compute_hmac(receipt)
        if not hmac.compare_digest(receipt.hmac or "", expected_hmac):
            return False
        # Ed25519 verify if signature present (lesson 18)
        sig = getattr(receipt, "signature", "") or ""
        if sig:
            try:
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

                pub_b64 = getattr(receipt, "public_key", "") or self._ed_pub_b64
                if not pub_b64:
                    return False
                pub_bytes = _b64url_decode(pub_b64)
                pub = Ed25519PublicKey.from_public_bytes(pub_bytes)
                canon = self._canonical_bytes(receipt)
                pub.verify(_b64url_decode(sig), canon)
            except Exception:
                return False
        return True

    def verify_chain(self, limit: int = 100) -> bool:
        """Verify hash chain integrity for recent receipts (append-only)."""
        recent = sorted(self._by_tool_call_id.values(), key=lambda r: r.timestamp)
        if len(recent) > limit:
            recent = recent[-limit:]
        prev = ""
        for r in recent:
            # Check hash recomputed matches stored (includes prev_hash)
            if r.hash != self._compute_hash(r):
                return False
            # Check prev_hash links
            if r.prev_hash and r.prev_hash != prev:
                # Allow first receipt prev_hash == "" and also allow gaps where prev_hash is empty (old receipts pre-chain)
                if prev != "":
                    return False
            prev = r.hash
        return True

    # ── Idempotency ────────────────────────────────────────
    # Tools that accept a caller-supplied task_id can be made safe to retry:
    # once a task_id completes in a session, the same call returns the cached
    # result instead of re-executing the side effect.

    def record_idempotent(self, task_id: str, session_id: str, result: str) -> None:
        """Record a completed task result keyed by (session_id, task_id)."""
        with self._lock:
            self._idempotent[f"{session_id}:{task_id}"] = result

    def get_idempotent(self, task_id: str, session_id: str) -> Optional[str]:
        """Return the cached result for a previously completed task, or None."""
        with self._lock:
            return self._idempotent.get(f"{session_id}:{task_id}")

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
