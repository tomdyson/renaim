from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ollama import OllamaConfig

CONFIG_KEYS = {"model", "ollama_url", "timeout", "preview_size"}
ENV_KEYS = {
    "model": "RENAIM_MODEL",
    "ollama_url": "RENAIM_OLLAMA_URL",
    "timeout": "RENAIM_TIMEOUT",
    "preview_size": "RENAIM_PREVIEW_SIZE",
}


@dataclass(frozen=True)
class Settings:
    model: str = OllamaConfig.model
    ollama_url: str = OllamaConfig.url
    timeout: float = OllamaConfig.timeout
    preview_size: int = 1024


def config_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home).expanduser() / "renaim" / "config.toml"
    return Path.home() / ".config" / "renaim" / "config.toml"


def read_config(path: Path | None = None) -> dict[str, Any]:
    path = path or config_path()
    if not path.exists():
        return {}
    with path.open("rb") as file:
        data = tomllib.load(file)
    return {key: data[key] for key in CONFIG_KEYS if key in data}


def write_config(values: dict[str, Any], path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key in sorted(values):
        value = values[key]
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        elif isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        else:
            lines.append(f"{key} = {value}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def parse_value(key: str, value: str) -> str | float | int:
    if key not in CONFIG_KEYS:
        raise ValueError(f"Unknown config key: {key}")
    if key == "timeout":
        parsed = float(value)
        if parsed <= 0:
            raise ValueError("timeout must be greater than 0")
        return parsed
    if key == "preview_size":
        parsed = int(value)
        if parsed <= 0:
            raise ValueError("preview_size must be greater than 0")
        return parsed
    return value


def set_config_value(key: str, value: str) -> None:
    values = read_config()
    values[key] = parse_value(key, value)
    write_config(values)


def unset_config_value(key: str) -> bool:
    if key not in CONFIG_KEYS:
        raise ValueError(f"Unknown config key: {key}")
    values = read_config()
    existed = key in values
    values.pop(key, None)
    write_config(values)
    return existed


def env_values() -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, env_key in ENV_KEYS.items():
        raw = os.environ.get(env_key)
        if raw is not None:
            values[key] = parse_value(key, raw)
    return values


def default_values() -> dict[str, Any]:
    settings = Settings()
    return {
        "model": settings.model,
        "ollama_url": settings.ollama_url,
        "timeout": settings.timeout,
        "preview_size": settings.preview_size,
    }


def resolved_values(cli_values: dict[str, Any] | None = None) -> dict[str, tuple[Any, str]]:
    cli_values = {key: value for key, value in (cli_values or {}).items() if value is not None}
    values: dict[str, tuple[Any, str]] = {key: (value, "default") for key, value in default_values().items()}
    for key, value in read_config().items():
        values[key] = (parse_config_value(key, value), "config")
    for key, value in env_values().items():
        values[key] = (value, "env")
    for key, value in cli_values.items():
        if key not in CONFIG_KEYS:
            raise ValueError(f"Unknown config key: {key}")
        values[key] = (value, "cli")
    return values


def resolve_settings(
    *,
    model: str | None = None,
    ollama_url: str | None = None,
    timeout: float | None = None,
    preview_size: int | None = None,
) -> Settings:
    resolved = resolved_values(
        {
            "model": model,
            "ollama_url": ollama_url,
            "timeout": timeout,
            "preview_size": preview_size,
        }
    )
    return Settings(
        model=str(resolved["model"][0]),
        ollama_url=str(resolved["ollama_url"][0]),
        timeout=float(resolved["timeout"][0]),
        preview_size=int(resolved["preview_size"][0]),
    )


def parse_config_value(key: str, value: Any) -> str | float | int:
    if key in {"model", "ollama_url"}:
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        return value
    if key == "timeout":
        return parse_value(key, str(value))
    if key == "preview_size":
        return parse_value(key, str(value))
    raise ValueError(f"Unknown config key: {key}")
