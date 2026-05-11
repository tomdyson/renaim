from pathlib import Path

from photo_renamer.cli import normalize_argv, resolved_db_path


def test_normalize_argv_inserts_run_for_path_shortcut():
    assert normalize_argv(["~/Photos", "--yolo"]) == ["run", "~/Photos", "--yolo"]


def test_normalize_argv_leaves_commands_and_options_alone():
    assert normalize_argv(["run", "~/Photos"]) == ["run", "~/Photos"]
    assert normalize_argv(["--help"]) == ["--help"]


def test_resolved_db_path_uses_explicit_path(tmp_path: Path):
    assert resolved_db_path(tmp_path / "photos", tmp_path / "audit.sqlite3") == tmp_path / "audit.sqlite3"
