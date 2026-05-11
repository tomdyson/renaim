from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

LLM_READABLE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class PreviewError(RuntimeError):
    pass


@contextlib.contextmanager
def preview_image(path: Path, max_size: int = 1024) -> Iterator[Path]:
    """Yield a small JPEG/PNG path for model input without modifying the original."""
    path = path.resolve()
    suffix = path.suffix.lower()

    if suffix in LLM_READABLE_EXTENSIONS and path.stat().st_size <= 2_500_000:
        yield path
        return

    with tempfile.NamedTemporaryFile(prefix="renaim-", suffix=".jpg", delete=False) as tmp:
        temp_path = Path(tmp.name)

    try:
        convert_to_jpeg(path, temp_path, max_size=max_size)
        yield temp_path
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()


def convert_to_jpeg(source: Path, target: Path, max_size: int = 1024) -> None:
    errors: list[str] = []

    if shutil.which("sips"):
        command = [
            "sips",
            "-Z",
            str(max_size),
            "-s",
            "format",
            "jpeg",
            str(source),
            "--out",
            str(target),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return
        errors.append((result.stderr or result.stdout).strip())

    if shutil.which("magick"):
        command = ["magick", str(source), "-auto-orient", "-resize", f"{max_size}x{max_size}>", str(target)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return
        errors.append((result.stderr or result.stdout).strip())

    details = "; ".join(error for error in errors if error) or "no converter available"
    raise PreviewError(f"Could not create preview for {source}: {details}")
