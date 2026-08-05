"""Tests for nally.tools.receipts — HMAC-signed tool execution receipts."""

import tempfile
from pathlib import Path

from nally.tools.receipts import Receipt, ReceiptStore


class TestReceipt:
    def test_create_receipt(self):
        r = Receipt("tc_1", "run_command", {"cmd": "ls"}, "file1.txt\nfile2.txt", True, 150.0)
        assert r.tool == "run_command"
        assert r.success is True
        assert r.duration_ms == 150.0

    def test_to_dict(self):
        r = Receipt("tc_1", "read_file", {"path": "test.txt"}, "hello", True, 10.0)
        d = r.to_dict()
        assert d["tool_call_id"] == "tc_1"
        assert d["tool"] == "read_file"
        assert d["success"] is True

    def test_from_dict(self):
        data = {
            "id": "abc123",
            "timestamp": 1234567890.0,
            "tool_call_id": "tc_1",
            "tool": "file_ops",
            "args": {"action": "delete"},
            "result": "Deleted file.txt",
            "success": True,
            "duration_ms": 25.0,
            "hash": "abc",
            "hmac": "def",
        }
        r = Receipt.from_dict(data)
        assert r.id == "abc123"
        assert r.tool == "file_ops"
        assert r.hash == "abc"


class TestReceiptStore:
    def _make_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ReceiptStore(
                store_path=Path(tmpdir) / "receipts.jsonl",
                secret_key="test-secret-key-for-hmac",
            )
            yield store

    def test_record_and_get(self):
        for store in self._make_store():
            r = store.record("tc_1", "run_command", {"cmd": "ls"}, "file1.txt", True, 50.0)
            assert r.hash  # Hash was computed
            assert r.hmac  # HMAC was computed

            found = store.get("tc_1")
            assert found is not None
            assert found.tool == "run_command"

    def test_verify_valid_receipt(self):
        for store in self._make_store():
            r = store.record("tc_1", "read_file", {}, "content", True, 10.0)
            assert store.verify(r) is True

    def test_verify_tampered_receipt(self):
        for store in self._make_store():
            r = store.record("tc_1", "read_file", {}, "content", True, 10.0)
            # Tamper with the result
            r.result = "TAMPERED"
            assert store.verify(r) is False

    def test_get_by_tool(self):
        for store in self._make_store():
            store.record("tc_1", "run_command", {}, "out1", True, 10.0)
            store.record("tc_2", "read_file", {}, "out2", True, 10.0)
            store.record("tc_3", "run_command", {}, "out3", True, 10.0)

            cmd_receipts = store.get_by_tool("run_command")
            assert len(cmd_receipts) == 2

    def test_get_recent(self):
        for store in self._make_store():
            store.record("tc_1", "tool_a", {}, "r1", True, 10.0)
            store.record("tc_2", "tool_b", {}, "r2", True, 10.0)
            store.record("tc_3", "tool_c", {}, "r3", True, 10.0)

            recent = store.get_recent(limit=2)
            assert len(recent) == 2

    def test_format_for_context(self):
        for store in self._make_store():
            r1 = store.record("tc_1", "run_command", {"cmd": "ls"}, "file1.txt", True, 50.0)
            r2 = store.record("tc_2", "file_ops", {"action": "delete"}, "Error: not found", False, 10.0)

            fmt = store.format_for_context([r1, r2])
            assert "OK" in fmt
            assert "FAILED" in fmt
            assert "run_command" in fmt
            assert "file_ops" in fmt

    def test_persistence(self):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "receipts.jsonl"
        key = "test-persistence-key"

        # Write
        store1 = ReceiptStore(store_path=path, secret_key=key)
        store1.record("tc_1", "run_command", {}, "output", True, 10.0)

        # Read back
        store2 = ReceiptStore(store_path=path, secret_key=key)
        found = store2.get("tc_1")
        assert found is not None
        assert found.tool == "run_command"
        assert store2.verify(found) is True
