from pathlib import Path

from photo_renamer.naming import clean_model_phrase, is_descriptive_filename, proposed_filename, slugify, unique_path


def test_slugify_removes_punctuation_and_normalizes_spaces():
    assert slugify("Family at table.") == "family-at-table"
    assert slugify("  3 Christmas dinner!!! ") == "christmas-dinner"


def test_clean_model_phrase_handles_simple_json():
    assert clean_model_phrase('{"name": "family at table"}') == "family at table"
    assert clean_model_phrase("Description: Dog on grass.") == "Dog on grass"


def test_proposed_filename_keeps_original_camera_name():
    assert proposed_filename(Path("P1120366.RW2"), "family at table") == "family-at-table_P1120366.RW2"


def test_unique_path_preserves_original_name_with_suffix(tmp_path):
    source = tmp_path / "P1120366.RW2"
    source.write_text("raw")
    target = tmp_path / "family-at-table_P1120366.RW2"
    target.write_text("existing")

    assert unique_path(target, source).name == "family-at-table-2_P1120366.RW2"


def test_is_descriptive_filename_skips_named_files_but_not_camera_files():
    assert is_descriptive_filename(Path("paddling-pool-1.jpg"))
    assert is_descriptive_filename(Path("little-girl-playing-with-mum_DSC02262.JPG"))
    assert not is_descriptive_filename(Path("DSC02262.JPG"))
    assert not is_descriptive_filename(Path("P1190726.jpg"))
