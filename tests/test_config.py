from pathlib import Path

import pytest

from photo_renamer.config import config_path, resolve_settings, set_config_value, unset_config_value


def test_config_path_uses_xdg_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert config_path() == tmp_path / "renaim" / "config.toml"


def test_config_env_and_cli_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    set_config_value("model", "config-model")
    set_config_value("ollama_url", "http://config.example:11434")
    set_config_value("prompt_guidance", "use UK English")
    monkeypatch.setenv("RENAIM_MODEL", "env-model")

    settings = resolve_settings(model="cli-model")

    assert settings.model == "cli-model"
    assert settings.ollama_url == "http://config.example:11434"
    assert settings.prompt_guidance == "use UK English"


def test_unset_config_value(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    set_config_value("preview_size", "768")
    assert resolve_settings().preview_size == 768

    assert unset_config_value("preview_size") is True
    assert resolve_settings().preview_size == 1024
