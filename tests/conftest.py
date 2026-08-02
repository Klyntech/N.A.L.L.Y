"""Shared test fixtures for NALLY test suite."""
import os
import sys
import tempfile
import pytest


# Ensure the project root is on sys.path
@pytest.fixture(scope="session", autouse=True)
def _project_root():
    """Add project root to sys.path so `nally` is importable."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_text():
    """Sample text for file/write tests."""
    return "Hello, this is test content for NALLY."


@pytest.fixture
def sample_code():
    """Sample Python code for code execution tests."""
    return "print('Hello from NALLY')"


# Markers for platform-specific tests
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "windows: marks tests that only run on Windows"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests requiring external services"
    )


# Skip Windows-only tests on non-Windows platforms
def pytest_collection_modifyitems(config, items):
    """Skip Windows-only tests when not on Windows."""
    if sys.platform != "win32":
        skip_windows = pytest.mark.skip(reason="only runs on Windows")
        for item in items:
            if "windows" in item.keywords:
                item.add_marker(skip_windows)
