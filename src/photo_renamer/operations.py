from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .database import Database
from .harmonize import HarmonizeGroup, harmonize_groups
from .images import PreviewError, preview_image
from .naming import clean_model_phrase, is_image, proposed_path, slugify, unique_path
from .ollama import OllamaClient, OllamaConfig, PROMPT_VERSION


@dataclass(frozen=True)
class ScanResult:
    found: int


def default_db_path(root: Path) -> Path:
    root = root.expanduser().resolve()
    directory = root.parent if root.is_file() else root
    legacy = directory / ".photo-renamer.sqlite3"
    if legacy.exists():
        return legacy
    if root.is_file():
        return root.parent / ".renaim.sqlite3"
    return root / ".renaim.sqlite3"


def iter_images(root: Path, include_hidden: bool = False) -> list[Path]:
    root = root.expanduser().resolve()
    if root.is_file():
        return [root] if is_image(root) else []

    images: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        if not include_hidden:
            dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for filename in filenames:
            if not include_hidden and filename.startswith("."):
                continue
            path = Path(directory) / filename
            if path.name in {".photo-renamer.sqlite3", ".renaim.sqlite3"}:
                continue
            if is_image(path):
                images.append(path)
    return sorted(images)


def scan(db: Database, root: Path, include_hidden: bool, console: Console) -> ScanResult:
    paths = iter_images(root, include_hidden=include_hidden)
    for path in paths:
        db.upsert_photo(root, path)
    console.print(f"Indexed [bold]{len(paths)}[/bold] image files.")
    return ScanResult(found=len(paths))


def suggest(
    db: Database,
    root: Path,
    model: str,
    ollama_url: str,
    timeout: float,
    limit: int | None,
    force: bool,
    preview_size: int,
    console: Console,
) -> int:
    client = OllamaClient(OllamaConfig(model=model, url=ollama_url, timeout=timeout))
    photos = db.photos_for_suggestions(root, force=force)
    if limit is not None:
        photos = photos[:limit]

    if not photos:
        existing = db.latest_suggestions(root, approved_only=False)
        if existing:
            console.print(
                f"No photos need suggestions. [bold]{len(existing)}[/bold] stored suggestions are ready to review/apply."
            )
        else:
            console.print("No photos need suggestions.")
        return 0

    count = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Generating suggestions", total=len(photos))
        for photo in photos:
            source = Path(photo.current_path)
            progress.update(task, description=f"Suggesting {source.name}")
            try:
                with preview_image(source, max_size=preview_size) as preview:
                    response = client.describe(preview)
                phrase = clean_model_phrase(response)
                slug = slugify(phrase)
                target = proposed_path(source, slug)
                db.add_suggestion(
                    photo_id=photo.id,
                    model=model,
                    prompt_version=PROMPT_VERSION,
                    prompt=OllamaConfig().prompt,
                    response=response,
                    slug=slug,
                    proposed_name=target.name,
                    proposed_path=str(target),
                )
                count += 1
            except (OSError, PreviewError, RuntimeError) as exc:
                db.set_photo_error(photo.id, str(exc))
                console.print(f"[red]Failed[/red] {source}: {exc}")
            finally:
                progress.advance(task)
    console.print(f"Stored [bold]{count}[/bold] suggestions.")
    return count


def show_suggestions(db: Database, root: Path, approved_only: bool, console: Console) -> list:
    suggestions = db.latest_suggestions(root, approved_only=approved_only)
    table = Table(title="Pending rename suggestions")
    table.add_column("ID", justify="right")
    table.add_column("Current")
    table.add_column("Proposed")
    table.add_column("Status")
    table.add_column("Model")
    for suggestion in suggestions:
        table.add_row(
            str(suggestion.id),
            Path(suggestion.current_path).name,
            Path(suggestion.proposed_path).name,
            suggestion.status,
            suggestion.model,
        )
    console.print(table)
    return suggestions


def review(db: Database, root: Path, console: Console) -> None:
    suggestions = show_suggestions(db, root, approved_only=False, console=console)
    if not suggestions:
        console.print("No pending suggestions.")
        return

    for suggestion in suggestions:
        current = Path(suggestion.current_path)
        proposed = Path(suggestion.proposed_path)
        console.print()
        console.print(f"[bold]{current}[/bold]")
        console.print(f"Model response: {suggestion.response!r}")
        console.print(f"Proposed: [green]{proposed.name}[/green]")
        action = Prompt.ask("Approve, edit, skip, or reject?", choices=["a", "e", "s", "r", "q"], default="a")
        if action == "q":
            break
        if action == "s":
            continue
        if action == "r":
            db.update_suggestion(suggestion.id, suggestion.slug, proposed.name, str(proposed), "rejected")
            continue
        if action == "e":
            phrase = Prompt.ask("New short phrase")
            slug = slugify(phrase)
            proposed = proposed_path(current, slug)
            db.update_suggestion(suggestion.id, slug, proposed.name, str(proposed), "approved")
            continue
        db.update_suggestion(suggestion.id, suggestion.slug, proposed.name, str(proposed), "approved")


def harmonize(
    db: Database,
    root: Path,
    threshold: float,
    min_group_size: int,
    yes: bool,
    dry_run: bool,
    approved_only: bool,
    console: Console,
) -> int:
    suggestions = db.latest_suggestions(root, approved_only=approved_only)
    if not suggestions:
        console.print("No suggestions to harmonize.")
        return 0

    groups = harmonize_groups([suggestion.slug for suggestion in suggestions], threshold=threshold, min_group_size=min_group_size)
    if not groups:
        console.print("No near-duplicate label groups found.")
        return 0

    by_slug = {suggestion.slug: [] for suggestion in suggestions}
    for suggestion in suggestions:
        by_slug.setdefault(suggestion.slug, []).append(suggestion)

    total_updated = 0
    for index, group in enumerate(groups, start=1):
        table = Table(title=f"Harmonize group {index}")
        table.add_column("Label")
        table.add_column("Count", justify="right")
        table.add_column("Example")
        for slug in group.slugs:
            matches = by_slug.get(slug, [])
            example = Path(matches[0].current_path).name if matches else ""
            table.add_row(slug, str(len(matches)), example)
        console.print(table)

        canonical = group.canonical
        if not yes:
            if not Confirm.ask(f"Merge these as '{canonical}'?", default=True):
                continue
            edited = Prompt.ask("Canonical label", default=canonical)
            canonical = slugify(edited)

        updates = suggestions_for_group(group, by_slug)
        if dry_run:
            console.print(f"Dry run: would update [bold]{len(updates)}[/bold] suggestions to [green]{canonical}[/green].")
            continue

        for suggestion in updates:
            current = Path(suggestion.current_path)
            target = proposed_path(current, canonical)
            db.update_suggestion(suggestion.id, canonical, target.name, str(target), suggestion.status)
            total_updated += 1
        console.print(f"Updated [bold]{len(updates)}[/bold] suggestions to [green]{canonical}[/green].")

    return total_updated


def suggestions_for_group(group: HarmonizeGroup, by_slug: dict[str, list]) -> list:
    suggestions = []
    for slug in group.slugs:
        suggestions.extend(by_slug.get(slug, []))
    return suggestions


def apply_renames(
    db: Database,
    root: Path,
    yes: bool,
    dry_run: bool,
    approved_only: bool,
    console: Console,
) -> int:
    suggestions = show_suggestions(db, root, approved_only=approved_only, console=console)
    if not suggestions:
        console.print("No suggestions to apply.")
        return 0

    if dry_run:
        console.print("Dry run only. No files renamed.")
        return 0

    if not yes and not Confirm.ask(f"Rename {len(suggestions)} files?", default=False):
        console.print("Cancelled.")
        return 0

    batch_id = db.create_batch("apply", root, dry_run=False)
    count = 0
    try:
        for suggestion in suggestions:
            source = Path(suggestion.current_path)
            if not source.exists():
                console.print(f"[yellow]Missing[/yellow] {source}")
                continue
            target = unique_path(Path(suggestion.proposed_path), source)
            if source == target:
                continue
            stat = source.stat()
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
            os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            db.record_rename(
                batch_id=batch_id,
                photo_id=suggestion.photo_id,
                suggestion_id=suggestion.id,
                old_path=source,
                new_path=target,
                old_size=stat.st_size,
                old_atime_ns=stat.st_atime_ns,
                old_mtime_ns=stat.st_mtime_ns,
            )
            count += 1
    finally:
        db.finish_batch(batch_id)

    console.print(f"Renamed [bold]{count}[/bold] files in batch [bold]{batch_id}[/bold].")
    return count


def undo(db: Database, root: Path, batch_id: int | None, console: Console, yes: bool) -> int:
    batch_id = batch_id or db.latest_apply_batch_id()
    if batch_id is None:
        console.print("No apply batch found.")
        return 0

    renames = db.applied_renames(batch_id)
    if not renames:
        console.print(f"No applied renames found for batch {batch_id}.")
        return 0

    if not yes and not Confirm.ask(f"Undo {len(renames)} renames from batch {batch_id}?", default=False):
        console.print("Cancelled.")
        return 0

    undo_batch_id = db.create_batch("undo", root, notes=f"Undo apply batch {batch_id}")
    count = 0
    try:
        for rename in renames:
            old_path = Path(rename.old_path)
            new_path = Path(rename.new_path)
            if not new_path.exists():
                console.print(f"[yellow]Missing renamed file[/yellow] {new_path}")
                continue
            if old_path.exists():
                console.print(f"[yellow]Original path already exists[/yellow] {old_path}")
                continue
            new_path.rename(old_path)
            os.utime(old_path, ns=(rename.old_atime_ns, rename.old_mtime_ns))
            db.mark_undone(rename.id, undo_batch_id, old_path, rename.photo_id, rename.suggestion_id)
            count += 1
    finally:
        db.finish_batch(undo_batch_id)

    console.print(f"Undid [bold]{count}[/bold] renames from batch [bold]{batch_id}[/bold].")
    return count
