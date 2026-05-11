from __future__ import annotations

import re
from pathlib import Path

IMAGE_EXTENSIONS = {
    ".3fr",
    ".ari",
    ".arw",
    ".avif",
    ".bmp",
    ".cr2",
    ".cr3",
    ".crw",
    ".dcr",
    ".dng",
    ".erf",
    ".gif",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".k25",
    ".kdc",
    ".mef",
    ".mos",
    ".mrw",
    ".nef",
    ".orf",
    ".pef",
    ".png",
    ".raf",
    ".raw",
    ".rw2",
    ".sr2",
    ".srf",
    ".srw",
    ".tif",
    ".tiff",
    ".webp",
    ".x3f",
}

RAW_EXTENSIONS = {
    ".3fr",
    ".ari",
    ".arw",
    ".cr2",
    ".cr3",
    ".crw",
    ".dcr",
    ".dng",
    ".erf",
    ".k25",
    ".kdc",
    ".mef",
    ".mos",
    ".mrw",
    ".nef",
    ".orf",
    ".pef",
    ".raf",
    ".raw",
    ".rw2",
    ".sr2",
    ".srf",
    ".srw",
    ".x3f",
}

CAMERA_FILENAME_RE = re.compile(
    r"^(?:dsc|dscf|dscn|img|image|p|pxl|sam|_mg|r?img)[-_]?\d+[a-z]?$|^\d{6,}$",
    re.IGNORECASE,
)
DESCRIPTIVE_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_descriptive_filename(path: Path) -> bool:
    stem = path.stem.strip().lower()
    if not stem:
        return False
    if CAMERA_FILENAME_RE.match(stem):
        return False
    tokens = [token for token in re.split(r"[^a-z]+", stem) if token and token not in DESCRIPTIVE_STOPWORDS]
    return len(tokens) >= 2


def slugify(text: str, fallback: str = "photo") -> str:
    text = text.strip().lower()
    text = re.sub(r"['\"`]", "", text)
    text = re.sub(r"[^a-z0-9\s_-]+", " ", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    text = re.sub(r"^\d+-", "", text)
    return text or fallback


def clean_model_phrase(response: str) -> str:
    text = response.strip()
    match = re.search(r'"(?:name|filename|description)"\s*:\s*"([^"]+)"', text)
    if match:
        text = match.group(1)
    text = text.splitlines()[0] if text else ""
    text = re.sub(r"^(?:filename|name|description)\s*:\s*", "", text, flags=re.I)
    return text.strip(" .,_-\"'")


def proposed_filename(path: Path, slug: str, max_length: int = 160) -> str:
    original_name = path.name
    slug = slugify(slug)
    suffix = f"_{original_name}"
    budget = max_length - len(suffix)
    if budget < 8:
        return original_name
    trimmed_slug = slug[:budget].rstrip("-")
    return f"{trimmed_slug}{suffix}"


def proposed_path(path: Path, slug: str, max_length: int = 160) -> Path:
    return path.with_name(proposed_filename(path, slug, max_length=max_length))


def unique_path(target: Path, source: Path) -> Path:
    if not target.exists() or target == source:
        return target

    name = target.name
    if "_" in name:
        slug, original = name.split("_", 1)
        for index in range(2, 10_000):
            candidate = target.with_name(f"{slug}-{index}_{original}")
            if not candidate.exists() or candidate == source:
                return candidate

    stem = target.stem
    suffix = target.suffix
    for index in range(2, 10_000):
        candidate = target.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists() or candidate == source:
            return candidate

    raise RuntimeError(f"Could not find an unused filename for {target}")
