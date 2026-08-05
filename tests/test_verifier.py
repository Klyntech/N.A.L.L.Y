"""Tests for nally.agent.verifier — claim verification against tool receipts."""


from nally.agent.verifier import ClaimVerifier, Verdict
from nally.tools.receipts import Receipt


class TestClaimVerifier:
    def setup_method(self):
        self.verifier = ClaimVerifier()

    def _make_receipt(self, tool_call_id="tc_1", tool="run_command", args=None, result="output", success=True):
        return Receipt(tool_call_id, tool, args or {}, result, success, 10.0)

    def test_backed_claim(self):
        """Agent says 'I ran the command' and there's a successful receipt."""
        receipts = [self._make_receipt("tc_1", "run_command", {"cmd": "ls"}, "file1.txt\nfile2.txt", True)]
        result = self.verifier.verify("I ran the command and got the file list.", receipts)
        assert result.is_honest
        assert result.backed_count >= 1

    def test_unsupported_claim(self):
        """Agent says 'I deleted the file' but no file_ops receipt exists."""
        receipts = [self._make_receipt("tc_1", "run_command", {"cmd": "ls"}, "ok", True)]
        result = self.verifier.verify("I deleted the folder from the desktop.", receipts)
        # Should find the delete claim but have no matching receipt
        assert any(f.verdict == Verdict.UNSUPPORTED for f in result.findings)

    def test_contradicted_claim(self):
        """Agent claims success but tool failed."""
        receipts = [self._make_receipt("tc_1", "file_ops", {}, "Error: permission denied", False)]
        result = self.verifier.verify("Done! The file was successfully deleted.", receipts)
        assert result.contradicted_count >= 1

    def test_no_claims_honest(self):
        """Agent says something with no action claims — always honest."""
        receipts = [self._make_receipt("tc_1", "run_command", {}, "ok", True)]
        result = self.verifier.verify("The weather is nice today.", receipts)
        assert result.is_honest

    def test_empty_receipts_unsupported(self):
        """Agent claims an action but no receipts at all."""
        result = self.verifier.verify("I ran the tests and they passed.", [])
        assert any(f.verdict == Verdict.UNSUPPORTED for f in result.findings)

    def test_trust_score(self):
        """Trust score = backed / total findings."""
        receipts = [
            self._make_receipt("tc_1", "run_command", {}, "ok", True),
            self._make_receipt("tc_2", "read_file", {}, "content", True),
        ]
        result = self.verifier.verify("I ran the command and read the file.", receipts)
        if result.findings:
            assert 0.0 <= result.trust_score <= 1.0
