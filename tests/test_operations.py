import os
from io import StringIO
from pathlib import Path

from rich.console import Console

from photo_renamer.database import Database
from photo_renamer.operations import apply_renames, harmonize, iter_images, scan, undo


def test_apply_and_undo_preserve_mtime_and_restore_path(tmp_path: Path):
    root = tmp_path / "photos"
    root.mkdir()
    image = root / "P1120366.jpg"
    image.write_bytes(b"fake jpeg")
    os.utime(image, ns=(1_700_000_001_000_000_000, 1_700_000_002_000_000_000))

    db = Database(tmp_path / "audit.sqlite3")
    console = Console(file=StringIO())
    try:
        scan(db, root, include_hidden=False, console=console)
        photo = db.photos_for_suggestions(root, force=True)[0]
        target = root / "family-at-table_P1120366.jpg"
        db.add_suggestion(
            photo_id=photo.id,
            model="test-model",
            prompt_version="test",
            prompt="test",
            response="family at table",
            slug="family-at-table",
            proposed_name=target.name,
            proposed_path=str(target),
        )

        assert apply_renames(db, root, yes=True, dry_run=False, approved_only=False, console=console) == 1
        assert not image.exists()
        assert target.exists()
        assert target.stat().st_mtime_ns == 1_700_000_002_000_000_000

        assert undo(db, root, batch_id=None, console=console, yes=True) == 1
        assert image.exists()
        assert not target.exists()
        assert image.stat().st_mtime_ns == 1_700_000_002_000_000_000
        suggestions = db.latest_suggestions(root)
        assert len(suggestions) == 1
        assert suggestions[0].status == "pending"
    finally:
        db.close()


def test_iter_images_streams_sorted_images_without_hidden_or_db_files(tmp_path: Path):
    root = tmp_path / "photos"
    root.mkdir()
    (root / "b.jpg").write_bytes(b"fake")
    (root / "a.RW2").write_bytes(b"fake")
    (root / ".hidden.jpg").write_bytes(b"fake")
    (root / ".renaim.sqlite3").write_bytes(b"db")
    (root / "notes.txt").write_text("no")

    assert [path.name for path in iter_images(root, include_hidden=False)] == ["a.RW2", "b.jpg"]


def test_repair_reopens_suggestions_from_old_undo_state(tmp_path: Path):
    root = tmp_path / "photos"
    root.mkdir()
    image = root / "P1120366.jpg"
    image.write_bytes(b"fake jpeg")
    target = root / "family-at-table_P1120366.jpg"

    db_path = tmp_path / "audit.sqlite3"
    db = Database(db_path)
    console = Console(file=StringIO())
    try:
        scan(db, root, include_hidden=False, console=console)
        photo = db.photos_for_suggestions(root, force=True)[0]
        suggestion_id = db.add_suggestion(
            photo_id=photo.id,
            model="test-model",
            prompt_version="test",
            prompt="test",
            response="family at table",
            slug="family-at-table",
            proposed_name=target.name,
            proposed_path=str(target),
        )
        assert apply_renames(db, root, yes=True, dry_run=False, approved_only=False, console=console) == 1
        assert undo(db, root, batch_id=None, console=console, yes=True) == 1
        db.conn.execute("UPDATE suggestions SET status = 'applied' WHERE id = ?", (suggestion_id,))
        db.conn.commit()
    finally:
        db.close()

    repaired = Database(db_path)
    try:
        suggestions = repaired.latest_suggestions(root)
        assert len(suggestions) == 1
        assert suggestions[0].status == "pending"
    finally:
        repaired.close()


def test_latest_apply_batch_ignores_already_undone_batches(tmp_path: Path):
    root = tmp_path / "photos"
    root.mkdir()
    image = root / "P1120366.jpg"
    image.write_bytes(b"fake jpeg")
    target = root / "family-at-table_P1120366.jpg"

    db = Database(tmp_path / "audit.sqlite3")
    console = Console(file=StringIO())
    try:
        scan(db, root, include_hidden=False, console=console)
        photo = db.photos_for_suggestions(root, force=True)[0]
        db.add_suggestion(
            photo_id=photo.id,
            model="test-model",
            prompt_version="test",
            prompt="test",
            response="family at table",
            slug="family-at-table",
            proposed_name=target.name,
            proposed_path=str(target),
        )

        assert apply_renames(db, root, yes=True, dry_run=False, approved_only=False, console=console) == 1
        assert db.latest_apply_batch_id() == 1
        assert undo(db, root, batch_id=None, console=console, yes=True) == 1
        assert db.latest_apply_batch_id() is None
    finally:
        db.close()


def test_harmonize_rewrites_near_duplicate_suggestions(tmp_path: Path):
    root = tmp_path / "photos"
    root.mkdir()
    paths = [root / "P1190726.jpg", root / "P1190728.jpg", root / "P1190734.jpg", root / "P1190741.jpg"]
    for path in paths:
        path.write_bytes(b"fake jpeg")

    db = Database(tmp_path / "audit.sqlite3")
    console = Console(file=StringIO())
    try:
        scan(db, root, include_hidden=False, console=console)
        slugs = ["live-music-performance", "live-music-performance", "live-band-performance", "band-playing-live-music"]
        for photo, slug in zip(db.photos_for_suggestions(root, force=True), slugs, strict=True):
            target = Path(photo.current_path).with_name(f"{slug}_{Path(photo.current_path).name}")
            db.add_suggestion(
                photo_id=photo.id,
                model="test-model",
                prompt_version="test",
                prompt="test",
                response=slug.replace("-", " "),
                slug=slug,
                proposed_name=target.name,
                proposed_path=str(target),
            )

        assert harmonize(
            db,
            root,
            threshold=0.4,
            min_group_size=2,
            yes=True,
            dry_run=False,
            approved_only=False,
            console=console,
        ) == 4

        suggestions = db.latest_suggestions(root)
        assert {suggestion.slug for suggestion in suggestions} == {"live-music-performance"}
        assert all(Path(suggestion.proposed_path).name.startswith("live-music-performance_") for suggestion in suggestions)
    finally:
        db.close()
