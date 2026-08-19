"""End-to-end engineering loop tests using FakeLLMBackend + FakeToolbox.

These prove the full pipeline works with no API key and no real filesystem
side effects beyond a temporary workspace directory.
"""

from __future__ import annotations

import json

import pytest

from nally.engineering import run_engineering
from nally.engineering.models import EngineeringError
from nally.engineering.protocol import FakeLLMBackend
from nally.engineering.toolbox import FakeToolbox
from nally.engineering.workspace import EngineeringWorkspace

MAIN_OK = (
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "\n"
    "def organize_by_extension(folder: str) -> dict:\n"
    "    try:\n"
    "        base = Path(folder)\n"
    "        if not base.exists():\n"
    "            raise ValueError(f'Folder not found: {folder}')\n"
    "        groups = {}\n"
    "        for item in base.iterdir():\n"
    "            if item.is_file():\n"
    "                ext = item.suffix or 'no-ext'\n"
    "                groups.setdefault(ext, []).append(item.name)\n"
    "        return groups\n"
    "    except PermissionError as exc:\n"
    "        raise RuntimeError(f'Permission denied: {exc}') from exc\n"
    "\n"
    "\n"
    "def main() -> int:\n"
    "    if len(sys.argv) < 2:\n"
    "        print('Usage: python main.py <folder>')\n"
    "        return 1\n"
    "    result = organize_by_extension(sys.argv[1])\n"
    "    for ext, names in sorted(result.items()):\n"
    "        print(f'{ext}: {len(names)} file(s)')\n"
    "    return 0\n"
    "\n"
    "\n"
    "if __name__ == '__main__':\n"
    "    raise SystemExit(main())\n"
)

MAIN_BUG = (
    "from pathlib import Path\n"
    "\n"
    "def organize_by_extension(folder: str) -> dict:\n"
    "    base = Path(folder)\n"
    "    groups = {}\n"
    "    for item in base.iterdir():\n"  # bug: no existence check, will raise on missing
    "        if item.is_file():\n"
    "            ext = item.suffix or 'no-ext'\n"
    "            groups.setdefault(ext, []).append(item.name)\n"
    "    return groups\n"
)

TEST_OK = (
    "from main import organize_by_extension\n"
    "\n"
    "def test_groups_files(tmp_path):\n"
    "    (tmp_path / 'a.txt').write_text('x')\n"
    "    (tmp_path / 'b.txt').write_text('y')\n"
    "    result = organize_by_extension(str(tmp_path))\n"
    "    assert '.txt' in result\n"
    "    assert len(result['.txt']) == 2\n"
    "\n"
    "def test_missing_folder_raises():\n"
    "    import pytest\n"
    "    with pytest.raises(ValueError):\n"
    "        organize_by_extension('/no/such/path/xyz')\n"
)


def _brainstorm():
    return json.dumps(
        {
            "approaches": [
                {
                    "id": "a1",
                    "title": "Naive script",
                    "category": "simple",
                    "summary": "One file, stdlib only",
                    "pros": ["simple"],
                    "cons": ["limited"],
                    "scores": {"feasibility": 5, "simplicity": 5, "maintainability": 3, "performance": 3, "novelty": 2},
                },
                {
                    "id": "a2",
                    "title": "Layered app",
                    "category": "robust_scalable",
                    "summary": "Structured, tested",
                    "pros": ["solid"],
                    "cons": ["more code"],
                    "scores": {"feasibility": 5, "simplicity": 3, "maintainability": 5, "performance": 4, "novelty": 3},
                },
                {
                    "id": "a3",
                    "title": "Streaming pipeline",
                    "category": "creative_unconventional",
                    "summary": "Treat files as a stream",
                    "pros": ["novel"],
                    "cons": ["risky"],
                    "scores": {"feasibility": 3, "simplicity": 2, "maintainability": 3, "performance": 5, "novelty": 5},
                },
            ]
        }
    )


def _design():
    return json.dumps(
        {
            "goal": "Organize files by extension",
            "architecture_summary": "CLI that groups files in a folder by suffix.",
            "components": [{"name": "cli", "responsibility": "entrypoint"}],
            "data_flow": "args -> scan -> group -> print",
            "tech_stack": ["python"],
            "dependencies": [],
            "file_plan": [
                {"path": "main.py", "purpose": "entrypoint", "language": "python"},
                {"path": "test_main.py", "purpose": "tests", "language": "python"},
            ],
        }
    )


def _test_plan():
    return json.dumps(
        {
            "framework": "pytest",
            "cases": [
                {"name": "test_groups_files", "description": "groups by ext", "target": "test_main.py"},
                {"name": "test_missing_folder_raises", "description": "raises on missing", "target": "test_main.py"},
            ],
        }
    )


def _implement(content_main, content_test):
    return json.dumps(
        {"files": [{"path": "main.py", "content": content_main}, {"path": "test_main.py", "content": content_test}]}
    )


def _finalize():
    return json.dumps({"known_limitations": ["Limited to local filesystem", "No concurrency support"]})


def _base_responses(initial_main):
    return {
        "clarify": json.dumps({"assumptions": ["Use Python 3.11", "Single file"], "questions": [], "needs_clarification": False}),
        "brainstorm": _brainstorm(),
        "design": _design(),
        "test_plan": _test_plan(),
        "implement": _implement(initial_main, TEST_OK),
        "finalize": _finalize(),
    }


def test_full_loop_success(tmp_path):
    backend = FakeLLMBackend(_base_responses(MAIN_OK), default="{}")
    toolbox = FakeToolbox(test_result=("3 passed", True), lint_result=("", True))
    ws = EngineeringWorkspace(base_dir=tmp_path, task="organize files by extension")
    result = run_engineering("Build a CLI tool that organizes files by extension", backend=backend, toolbox=toolbox, workspace=ws)

    # Progression checks
    assert result.success is True
    assert result.refinements == 0
    assert "main.py" in result.artifacts
    assert "test_main.py" in result.artifacts
    # Best approach selected (robust wins by weighted score)
    assert result.chosen_approach is not None
    assert result.chosen_approach.id == "a2"
    # Artifacts persisted
    assert ws.dir.joinpath("README.md").exists()
    assert ws.dir.joinpath("engineering_manifest.json").exists()
    assert ws.dir.joinpath("scorecard.json").exists()
    # README content sanity
    readme = ws.dir.joinpath("README.md").read_text(encoding="utf-8")
    assert "Scorecard" in readme
    assert "Known Limitations" in readme
    assert "organizes" in readme.lower()
    # Manifest records stages including done
    manifest = json.loads(ws.dir.joinpath("engineering_manifest.json").read_text(encoding="utf-8"))
    stage_names = [s["stage"] for s in manifest["stages"]]
    assert "intake" in stage_names
    assert "brainstorm" in stage_names
    assert "done" in stage_names
    # Backend was driven through the expected stages
    stages_called = {c["stage"] for c in backend.calls}
    assert {"clarify", "brainstorm", "design", "test_plan", "implement", "finalize"} <= stages_called


def test_full_loop_refines_on_failure(tmp_path):
    responses = _base_responses(MAIN_BUG)
    responses["refine"] = _implement(MAIN_OK, TEST_OK)  # fixed version
    backend = FakeLLMBackend(responses, default="{}")
    # First test run fails, second (after refine) passes.
    toolbox = FakeToolbox(test_result=[("1 failed", False), ("3 passed", True)], lint_result=("", True))
    ws = EngineeringWorkspace(base_dir=tmp_path, task="organize files")
    result = run_engineering("Build a CLI tool that organizes files by extension", backend=backend, toolbox=toolbox, workspace=ws)

    assert result.refinements == 1
    assert result.success is True
    # The refined (correct) main.py content was written.
    assert MAIN_OK in {c for _, c in toolbox.writes} or any(MAIN_OK in c for _, c in toolbox.writes)


def test_full_loop_honors_refinement_cap(tmp_path):
    responses = _base_responses(MAIN_BUG)
    responses["refine"] = _implement(MAIN_BUG, TEST_OK)  # still broken after refine
    backend = FakeLLMBackend(responses, default="{}")
    # Tests always fail; loop must stop at the cap.
    toolbox = FakeToolbox(test_result=("1 failed", False), lint_result=("", True))
    ws = EngineeringWorkspace(base_dir=tmp_path, task="organize files")
    result = run_engineering(
        "Build a CLI tool that organizes files by extension",
        backend=backend,
        toolbox=toolbox,
        workspace=ws,
        max_refinements=2,
    )

    assert result.refinements == 2
    assert result.success is False


def test_loop_aborts_cleanly(tmp_path):
    backend = FakeLLMBackend({}, default="{}")
    toolbox = FakeToolbox()
    ws = EngineeringWorkspace(base_dir=tmp_path, task="organize files")

    def always_abort():
        return True

    with pytest.raises(EngineeringError):
        run_engineering(
            "Build a CLI tool",
            backend=backend,
            toolbox=toolbox,
            workspace=ws,
            abort_fn=always_abort,
        )
    # Manifest still persisted in finally.
    assert ws.manifest_path.exists()
