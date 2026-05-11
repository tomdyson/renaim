# renaim

Rename photos with a local Ollama vision model, while keeping a SQLite audit
trail that can undo rename batches later.

The default filename format keeps the camera filename:

```text
family-at-table_P1120366.RW2
```

The tool never rewrites image contents. RAW files and large images are converted
to small temporary JPEG previews for the model, then the original file is
renamed. Filesystem access and modification times are restored after each
rename. EXIF data inside the original file is not changed.

## Requirements

- macOS `sips` for RAW/HEIC/large image preview conversion, or ImageMagick
  `magick` as a fallback.
- Ollama running locally.
- A multimodal Ollama model, for example:

```bash
ollama pull gemma4:e4b
```

If you prefer another model, pass `--model`.

## Install for development

```bash
uv sync --extra dev
uv run renaim --help
```

The package exposes the `renaim` command.

## Typical workflow

Index files without touching the model:

```bash
uv run renaim scan ~/Pictures/Photos
```

`scan` streams progress while walking directories, which is useful on NAS
folders where the first traversal can take a while.

Generate suggestions:

```bash
uv run renaim suggest ~/Pictures/Photos --model gemma4:e4b
```

If the audit DB already exists, `suggest` reuses the existing index. Pass
`--rescan` to walk the folder again before suggesting:

```bash
uv run renaim suggest ~/Pictures/Photos --rescan
```

Review and optionally edit suggestions:

```bash
uv run renaim review ~/Pictures/Photos
```

Harmonize near-duplicate labels across the folder:

```bash
uv run renaim harmonize ~/Pictures/Photos
```

Apply approved or pending suggestions:

```bash
uv run renaim apply ~/Pictures/Photos
```

Undo the latest apply batch:

```bash
uv run renaim undo ~/Pictures/Photos
```

Show previous batches:

```bash
uv run renaim batches ~/Pictures/Photos
```

## All-night NAS run

For unattended operation, keep the audit DB somewhere local and explicitly opt in
to harmonizing and renaming:

```bash
uv run renaim run /Volumes/photos/archive \
  --db ~/.local/state/renaim/archive.sqlite3 \
  --model gemma4:e4b \
  --harmonize \
  --apply \
  --yes
```

Without `--apply`, `run` only scans and stores suggestions.

The shortcut form is:

```bash
uv run renaim run /Volumes/photos/archive \
  --db ~/.local/state/renaim/archive.sqlite3 \
  --model gemma4:e4b \
  --yolo
```

`--yolo` means `--harmonize --apply --yes`.

Because `run` is the default command, this is equivalent:

```bash
uvx renaim /Volumes/photos/archive --yolo
```

## Audit database

By default the database is created as `.renaim.sqlite3` inside the target
directory. Existing `.photo-renamer.sqlite3` databases are still used when found.
Use `--db PATH` to put it elsewhere.

The database records:

- original and current paths
- file size and filesystem mtime
- model name, prompt version, raw model response, slug, and proposed path
- apply batches and each old path/new path pair
- undo batches

Undo only reverses rename batches made by this tool. It does not try to infer or
repair manual moves made afterward.

## Weaknesses and limits

This is still a pragmatic local tool, not a full DAM/photo-library system.

- **Ollama-only backend.** Model calls currently go through Ollama's
  `/api/generate` API. Other local runtimes or hosted APIs would need a backend
  abstraction.
- **Preview conversion depends on local tools.** On macOS it uses `sips`; if
  available, ImageMagick `magick` is used as a fallback. RAW support on Linux or
  NAS hosts will depend on installing a converter that can read your camera
  files.
- **Model output is approximate.** Vision models can be vague, wrong, or
  inconsistent across similar images. `renaim harmonize` helps normalize labels
  within a folder, but it does not understand your whole photo library.
- **No embedded metadata writes.** The tool does not write the original filename
  into EXIF/XMP metadata. The SQLite audit DB is the source of truth for undo and
  history.
- **No full-file hashing by default.** To keep NAS scans fast, file identity is
  tracked mainly by path, size, and mtime. This is weaker than content hashes if
  files are moved or modified outside the tool.
- **Undo is scoped to tool-managed renames.** If files are manually moved,
  deleted, or renamed after an apply batch, undo may skip them or warn rather
  than reconstructing intent.
- **Sidecars are not renamed yet.** RAW sidecar formats such as `.xmp`, `.dop`,
  `.pp3`, or catalog files are not currently moved with the image.
- **No concurrent-run locking yet.** Running multiple `renaim` processes against
  the same directory/database is not supported.
- **The audit DB is local state.** If the DB is deleted, rename history and undo
  information are lost. For NAS use, keep the DB somewhere backed up.

## Config

Runtime settings use this precedence:

```text
CLI flags > environment variables > ~/.config/renaim/config.toml > defaults
```

Show the effective config:

```bash
uv run renaim config show
```

Set your usual model:

```bash
uv run renaim config set model gemma4:e4b
uv run renaim config set ollama_url http://localhost:11434
uv run renaim config set timeout 180
uv run renaim config set preview_size 1024
```

Unset a value:

```bash
uv run renaim config unset model
```

Supported environment variables:

```bash
RENAIM_MODEL=gemma4:e4b
RENAIM_OLLAMA_URL=http://localhost:11434
RENAIM_TIMEOUT=180
RENAIM_PREVIEW_SIZE=1024
```

## Useful commands

Limit a trial run:

```bash
uv run renaim suggest ~/Pictures/Photos --limit 20
```

Use another Ollama server or model:

```bash
uv run renaim suggest ~/Pictures/Photos \
  --ollama-url http://nas.local:11434 \
  --model llava:13b
```

Apply only suggestions explicitly approved in `review`:

```bash
uv run renaim apply ~/Pictures/Photos --approved-only
```

Preview label harmonization without changing suggestions:

```bash
uv run renaim harmonize ~/Pictures/Photos --dry-run
```

For unattended runs, accept the default canonical label for each near-duplicate
group:

```bash
uv run renaim harmonize ~/Pictures/Photos --yes
```
