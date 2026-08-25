"""Tests for nally.tools.files — ReadFile and FileOps."""

import os
import tempfile
import pytest
from pathlib import Path
from nally.tools.files import ReadFile, FileOps, _is_safe_write_path, _validate_file


@pytest.fixture
def read_file():
    return ReadFile()


@pytest.fixture
def file_ops():
    return FileOps()


class TestPathSafety:
    def test_cwd_is_safe(self):
        assert _is_safe_write_path(Path.cwd()) is True

    def test_home_not_safe(self):
        """Home directory itself should not be writable (blocks ~/.ssh etc)."""
        assert _is_safe_write_path(Path.home()) is False

    def test_desktop_is_safe(self):
        assert _is_safe_write_path(Path.home() / "Desktop") is True

    def test_documents_is_safe(self):
        assert _is_safe_write_path(Path.home() / "Documents") is True

    def test_random_path_not_safe(self):
        assert _is_safe_write_path(Path("/etc/passwd")) is False


class TestReadFile:
    def test_file_not_found(self, read_file):
        result = read_file.execute(file_path="/nonexistent/file.txt")
        assert "Error" in result
        assert "not found" in result.lower()

    def test_empty_path(self, read_file):
        result = read_file.execute(file_path="")
        assert "Error" in result

    def test_sensitive_dir_blocked(self, read_file):
        result = read_file.execute(file_path=str(Path.home() / ".ssh" / "id_rsa"))
        assert "Error" in result
        assert "denied" in result.lower()

    def test_read_existing_file(self, read_file):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content here")
            path = f.name
        try:
            result = read_file.execute(file_path=path)
            assert "test content here" in result
        finally:
            os.unlink(path)

    def test_large_file_truncated(self, read_file):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("x" * 6000)
            path = f.name
        try:
            result = read_file.execute(file_path=path)
            assert "truncated" in result.lower() or len(result) < 6000
        finally:
            os.unlink(path)


class TestFileOps:
    def test_empty_action(self, file_ops):
        result = file_ops.execute(action="")
        assert "Error" in result

    def test_write_safe_path(self, file_ops):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.txt"
            result = file_ops.execute(action="write", file_path=str(path), content="hello")
            assert "Wrote" in result
            assert path.read_text() == "hello"

    def test_list_directory(self, file_ops):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = file_ops.execute(action="list", file_path=tmpdir)
            assert isinstance(result, str)

    def test_mkdir(self, file_ops):
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "subdir"
            result = file_ops.execute(action="mkdir", file_path=str(new_dir))
            assert "Created" in result
            assert new_dir.is_dir()

    def test_delete_file(self, file_ops):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "to_delete.txt"
            path.write_text("bye")
            result = file_ops.execute(action="delete", file_path=str(path))
            assert "Deleted" in result
            assert not path.exists()

    def test_unknown_action(self, file_ops):
        result = file_ops.execute(action="unknown_action")
        assert "Error" in result

    def test_write_path_outside_allowed(self, file_ops):
        result = file_ops.execute(action="write", file_path="/etc/passwd", content="bad")
        assert "Error" in result
        assert "outside" in result.lower()


class TestValidateFile:
    def test_clean_python(self):
        warnings = _validate_file(Path("test.py"), "x = 1\n")
        assert warnings == ""

    def test_html_missing_meta(self):
        warnings = _validate_file(Path("test.html"), "<html><body>hi</body></html>")
        assert "meta" in warnings.lower() or "EMOJI" in warnings

    def test_css_brace_mismatch(self):
        warnings = _validate_file(Path("test.css"), "body { color: red;")
        assert "Brace mismatch" in warnings

    def test_js_bare_var(self):
        warnings = _validate_file(Path("test.js"), "var x = 1;")
        assert "var" in warnings.lower()
