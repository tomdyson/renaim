from photo_renamer.cli import normalize_argv


def test_normalize_argv_inserts_run_for_path_shortcut():
    assert normalize_argv(["~/Photos", "--yolo"]) == ["run", "~/Photos", "--yolo"]


def test_normalize_argv_leaves_commands_and_options_alone():
    assert normalize_argv(["run", "~/Photos"]) == ["run", "~/Photos"]
    assert normalize_argv(["--help"]) == ["--help"]
