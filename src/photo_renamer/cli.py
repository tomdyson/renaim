from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .config import CONFIG_KEYS, config_path, resolved_values, resolve_settings, set_config_value, unset_config_value
from .database import Database
from .operations import apply_renames, default_db_path, review as review_suggestions
from .operations import harmonize as harmonize_operation
from .operations import scan as scan_operation
from .operations import show_suggestions, suggest as suggest_operation
from .operations import undo as undo_operation

app = typer.Typer(no_args_is_help=True, help="Rename photos with local Ollama vision models.")
config_app = typer.Typer(help="Manage user defaults.")
app.add_typer(config_app, name="config")
console = Console()

COMMANDS = {
    "apply",
    "batches",
    "config",
    "harmonize",
    "list",
    "review",
    "run",
    "scan",
    "suggest",
    "undo",
}


def open_db(root: Path, db_path: Path | None) -> Database:
    path = db_path.expanduser() if db_path else default_db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return Database(path)


def resolved_db_path(root: Path, db_path: Path | None) -> Path:
    return db_path.expanduser() if db_path else default_db_path(root)


RootArg = Annotated[Path, typer.Argument(help="Photo file or directory to process.")]
DbOpt = Annotated[Path | None, typer.Option("--db", help="SQLite audit database path.")]
HiddenOpt = Annotated[bool, typer.Option("--include-hidden", help="Include hidden files and directories.")]
ModelOpt = Annotated[
    str | None,
    typer.Option("--model", "-m", help="Ollama model name. Overrides RENAIM_MODEL and config."),
]
UrlOpt = Annotated[
    str | None,
    typer.Option("--ollama-url", help="Base Ollama URL. Overrides RENAIM_OLLAMA_URL and config."),
]
TimeoutOpt = Annotated[
    float | None,
    typer.Option("--timeout", help="Ollama request timeout in seconds. Overrides RENAIM_TIMEOUT and config."),
]
PreviewSizeOpt = Annotated[
    int | None,
    typer.Option("--preview-size", help="Maximum preview image dimension. Overrides RENAIM_PREVIEW_SIZE and config."),
]


@config_app.command("path")
def config_path_command() -> None:
    """Show the user config file path."""
    console.print(config_path())


@config_app.command("show")
def config_show() -> None:
    """Show effective config values and their sources."""
    table = Table(title="renaim config")
    table.add_column("Key")
    table.add_column("Value")
    table.add_column("Source")
    for key, (value, source) in resolved_values().items():
        table.add_row(key, str(value), source)
    console.print(table)
    console.print(f"Config file: [dim]{config_path()}[/dim]")


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Set a config value."""
    if key not in CONFIG_KEYS:
        raise typer.BadParameter(f"unknown key {key!r}; expected one of {', '.join(sorted(CONFIG_KEYS))}")
    try:
        set_config_value(key, value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Set [bold]{key}[/bold] in [dim]{config_path()}[/dim].")


@config_app.command("unset")
def config_unset(key: str) -> None:
    """Unset a config value."""
    if key not in CONFIG_KEYS:
        raise typer.BadParameter(f"unknown key {key!r}; expected one of {', '.join(sorted(CONFIG_KEYS))}")
    unset_config_value(key)
    console.print(f"Unset [bold]{key}[/bold] in [dim]{config_path()}[/dim].")


@config_app.command("file")
def config_file() -> None:
    """Print the raw config file contents."""
    path = config_path()
    if not path.exists():
        console.print(f"No config file at [dim]{path}[/dim].")
        return
    console.print(path.read_text(encoding="utf-8"))


@app.command()
def scan(root: RootArg, db: DbOpt = None, include_hidden: HiddenOpt = False) -> None:
    """Index image files without asking the model or renaming anything."""
    database = open_db(root, db)
    try:
        scan_operation(database, root, include_hidden=include_hidden, console=console)
        console.print(f"Audit database: [dim]{database.path}[/dim]")
    finally:
        database.close()


@app.command()
def suggest(
    root: RootArg,
    db: DbOpt = None,
    include_hidden: HiddenOpt = False,
    model: ModelOpt = None,
    ollama_url: UrlOpt = None,
    timeout: TimeoutOpt = None,
    limit: Annotated[int | None, typer.Option("--limit", help="Maximum number of photos to suggest.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Create fresh suggestions even when one already exists.")] = False,
    preview_size: PreviewSizeOpt = None,
    rescan: Annotated[
        bool,
        typer.Option("--rescan", help="Scan the directory before suggesting. Defaults on only when no DB exists."),
    ] = False,
) -> None:
    """Generate and store rename suggestions."""
    settings = resolve_settings(model=model, ollama_url=ollama_url, timeout=timeout, preview_size=preview_size)
    db_path = resolved_db_path(root, db)
    should_scan = rescan or not db_path.exists()
    database = open_db(root, db)
    try:
        if should_scan:
            scan_operation(database, root, include_hidden=include_hidden, console=console)
        else:
            console.print(f"Using existing index from [dim]{database.path}[/dim]. Pass [bold]--rescan[/bold] to scan first.")
        suggest_operation(
            database,
            root,
            model=settings.model,
            ollama_url=settings.ollama_url,
            timeout=settings.timeout,
            limit=limit,
            force=force,
            preview_size=settings.preview_size,
            console=console,
        )
        console.print(f"Audit database: [dim]{database.path}[/dim]")
    finally:
        database.close()


@app.command()
def review(root: RootArg, db: DbOpt = None) -> None:
    """Approve, edit, skip, or reject stored suggestions."""
    database = open_db(root, db)
    try:
        review_suggestions(database, root, console=console)
    finally:
        database.close()


@app.command("list")
def list_suggestions(
    root: RootArg,
    db: DbOpt = None,
    approved_only: Annotated[bool, typer.Option("--approved-only", help="Show only approved suggestions.")] = False,
) -> None:
    """Show pending suggestions."""
    database = open_db(root, db)
    try:
        show_suggestions(database, root, approved_only=approved_only, console=console)
    finally:
        database.close()


@app.command()
def harmonize(
    root: RootArg,
    db: DbOpt = None,
    threshold: Annotated[
        float,
        typer.Option("--threshold", help="Slug similarity threshold for grouping near-duplicates."),
    ] = 0.4,
    min_group_size: Annotated[
        int,
        typer.Option("--min-group-size", help="Minimum distinct labels required before a group is shown."),
    ] = 2,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Accept default canonical labels without prompting.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show groups without updating suggestions.")] = False,
    approved_only: Annotated[bool, typer.Option("--approved-only", help="Harmonize only approved suggestions.")] = False,
) -> None:
    """Merge near-duplicate labels before applying renames."""
    database = open_db(root, db)
    try:
        harmonize_operation(
            database,
            root,
            threshold=threshold,
            min_group_size=min_group_size,
            yes=yes,
            dry_run=dry_run,
            approved_only=approved_only,
            console=console,
        )
    finally:
        database.close()


@app.command()
def apply(
    root: RootArg,
    db: DbOpt = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not prompt before applying.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview the apply step without renaming.")] = False,
    approved_only: Annotated[bool, typer.Option("--approved-only", help="Apply only suggestions approved during review.")] = False,
) -> None:
    """Apply stored suggestions and record an undoable batch."""
    database = open_db(root, db)
    try:
        apply_renames(database, root, yes=yes, dry_run=dry_run, approved_only=approved_only, console=console)
    finally:
        database.close()


@app.command()
def run(
    root: RootArg,
    db: DbOpt = None,
    include_hidden: HiddenOpt = False,
    model: ModelOpt = None,
    ollama_url: UrlOpt = None,
    timeout: TimeoutOpt = None,
    limit: Annotated[int | None, typer.Option("--limit", help="Maximum number of photos to process.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Create fresh suggestions even when one already exists.")] = False,
    preview_size: PreviewSizeOpt = None,
    harmonize_changes: Annotated[
        bool,
        typer.Option("--harmonize", help="Merge near-duplicate labels before applying."),
    ] = False,
    apply_changes: Annotated[bool, typer.Option("--apply", help="Rename files after suggestions are generated.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not prompt before applying.")] = False,
    yolo: Annotated[
        bool,
        typer.Option("--yolo", help="Shortcut for --harmonize --apply --yes."),
    ] = False,
) -> None:
    """Scan, suggest, and optionally apply in one resumable command."""
    if yolo:
        harmonize_changes = True
        apply_changes = True
        yes = True

    settings = resolve_settings(model=model, ollama_url=ollama_url, timeout=timeout, preview_size=preview_size)
    database = open_db(root, db)
    try:
        scan_operation(database, root, include_hidden=include_hidden, console=console)
        suggest_operation(
            database,
            root,
            model=settings.model,
            ollama_url=settings.ollama_url,
            timeout=settings.timeout,
            limit=limit,
            force=force,
            preview_size=settings.preview_size,
            console=console,
        )
        if harmonize_changes:
            harmonize_operation(
                database,
                root,
                threshold=0.4,
                min_group_size=2,
                yes=yes,
                dry_run=False,
                approved_only=False,
                console=console,
            )
        if apply_changes:
            apply_renames(database, root, yes=yes, dry_run=False, approved_only=False, console=console)
        else:
            next_steps = "[bold]renaim review[/bold] or [bold]renaim apply[/bold]"
            if not harmonize_changes:
                next_steps = "[bold]renaim harmonize[/bold], [bold]renaim review[/bold], or [bold]renaim apply[/bold]"
            console.print(f"Suggestions stored. Run {next_steps} when ready.")
        console.print(f"Audit database: [dim]{database.path}[/dim]")
    finally:
        database.close()


@app.command()
def undo(
    root: RootArg,
    db: DbOpt = None,
    batch: Annotated[int | None, typer.Option("--batch", "-b", help="Apply batch ID to undo. Defaults to latest.")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not prompt before undoing.")] = False,
) -> None:
    """Undo a rename batch recorded by this tool."""
    database = open_db(root, db)
    try:
        undo_operation(database, root, batch_id=batch, console=console, yes=yes)
    finally:
        database.close()


@app.command()
def batches(
    root: RootArg,
    db: DbOpt = None,
    limit: Annotated[int, typer.Option("--limit", help="Number of batches to show.")] = 20,
) -> None:
    """Show recent audit batches."""
    database = open_db(root, db)
    try:
        table = Table(title="Recent batches")
        table.add_column("ID", justify="right")
        table.add_column("Action")
        table.add_column("Model")
        table.add_column("Dry run")
        table.add_column("Renames", justify="right")
        table.add_column("Active", justify="right")
        table.add_column("Started")
        table.add_column("Finished")
        for row in database.batches(limit=limit):
            table.add_row(
                str(row["id"]),
                row["action"],
                row["model"] or "",
                "yes" if row["dry_run"] else "no",
                str(row["rename_count"]),
                str(row["active_count"]),
                row["started_at"],
                row["finished_at"] or "",
            )
        console.print(table)
    finally:
        database.close()


def normalize_argv(args: list[str]) -> list[str]:
    """Allow `renaim PATH` as shorthand for `renaim run PATH`."""
    if not args:
        return args
    first = args[0]
    if first in COMMANDS or first.startswith("-"):
        return args
    return ["run", *args]


def main() -> None:
    app(args=normalize_argv(sys.argv[1:]), prog_name="renaim")


if __name__ == "__main__":
    main()
