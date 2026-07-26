"""Test profile migration flow."""
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

from nally.memory.store import MemoryRepository, migrate_profile, RECOGNIZED_PROFILE_KEYS


def test_migration():
    tmpdir = Path(tempfile.mkdtemp())
    data_dir = tmpdir / "data"
    data_dir.mkdir()

    profile = {
        "name": "Clinton",
        "preferred_name": "Clinton",
        "aliases": ["Klyntech", "Klynvybz"],
        "age": 17,
        "location": "Lagos",
        "occupation": "Developer",
        "goals": ["Build a company", "Be global"],
        "notes": "Testing migration",
    }
    (data_dir / "user_profile.json").write_text(json.dumps(profile, indent=2))

    with patch("nally.memory.store.DATA_DIR", data_dir):
        store = MemoryRepository(db_path=data_dir / "test_memory.db")
        migrate_profile(store)

        # File renamed
        assert (data_dir / "user_profile.json.migrated").exists(), "File not renamed"
        assert not (data_dir / "user_profile.json").exists(), "Original still exists"

        # Data stored
        result = store.recall(category="profile")
        assert isinstance(result, dict)
        assert result.get("name") == "Clinton"
        assert result.get("age") == "17"
        assert result.get("location") == "Lagos"
        print(f"Stored {len(result)} profile fields")

    shutil.rmtree(tmpdir)
    print("test_migration PASSED")


def test_no_profile():
    tmpdir = Path(tempfile.mkdtemp())
    data_dir = tmpdir / "data"
    data_dir.mkdir()

    with patch("nally.memory.store.DATA_DIR", data_dir):
        store = MemoryRepository(db_path=data_dir / "test_memory.db")
        migrate_profile(store)  # should be a no-op
        result = store.recall(category="profile")
        assert result is None or result == {}, f"Expected empty, got {result}"

    shutil.rmtree(tmpdir)
    print("test_no_profile PASSED")


def test_recognized_keys():
    assert "name" in RECOGNIZED_PROFILE_KEYS
    assert "age" in RECOGNIZED_PROFILE_KEYS
    assert "goals" in RECOGNIZED_PROFILE_KEYS
    assert "notes" in RECOGNIZED_PROFILE_KEYS
    assert len(RECOGNIZED_PROFILE_KEYS) == 19
    print("test_recognized_keys PASSED")


def test_idempotent():
    tmpdir = Path(tempfile.mkdtemp())
    data_dir = tmpdir / "data"
    data_dir.mkdir()

    profile = {"name": "Clinton", "age": 17}
    (data_dir / "user_profile.json").write_text(json.dumps(profile))

    with patch("nally.memory.store.DATA_DIR", data_dir):
        store = MemoryRepository(db_path=data_dir / "test_memory.db")
        migrate_profile(store)
        migrate_profile(store)  # second call should be no-op

        result = store.recall(category="profile")
        assert result.get("name") == "Clinton"

    shutil.rmtree(tmpdir)
    print("test_idempotent PASSED")


if __name__ == "__main__":
    test_migration()
    test_no_profile()
    test_recognized_keys()
    test_idempotent()
    print("\nAll tests passed")
