"""config.py: settings and .env loading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.config import ConfigError, key_status, load_env, load_settings


def write(project: Path, name: str, text: str) -> None:
    (project / "config" / name).write_text(text, encoding="utf-8")


def test_valid_settings_load(project: Path) -> None:
    settings = load_settings(project)
    assert settings.caps == {"apollo": {"credits": 10}, "google_places": {"requests": 5}}
    assert settings.root == project


def test_missing_settings_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="settings.yaml"):
        load_settings(tmp_path)


def test_unknown_settings_key(project: Path) -> None:
    write(project, "settings.yaml", "caps: {apollo: {credits: 1}}\ndatabse: y\n")
    with pytest.raises(ConfigError, match="databse"):
        load_settings(project)


@pytest.mark.parametrize("value", ["-1", "ten", "true", "1.5"])
def test_bad_cap(project: Path, value: str) -> None:
    write(project, "settings.yaml", f"caps:\n  apollo:\n    credits: {value}\n")
    with pytest.raises(ConfigError, match="caps.apollo.credits"):
        load_settings(project)


def test_settings_not_a_mapping(project: Path) -> None:
    write(project, "settings.yaml", "- just\n- a list\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_settings(project)


def test_load_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALREADY_SET", "keep")
    monkeypatch.delenv("NEW_ONE", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        '# comment\n\nNEW_ONE=hello\nALREADY_SET=replace\nQUOTED="a b"\n', encoding="utf-8"
    )
    load_env(env)
    assert os.environ["NEW_ONE"] == "hello"
    assert os.environ["ALREADY_SET"] == "keep"
    assert os.environ["QUOTED"] == "a b"


def test_load_env_missing_file_is_fine(tmp_path: Path) -> None:
    load_env(tmp_path / ".env")


def test_key_status_only_booleans(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "secret-123")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    status = key_status()
    assert status["APOLLO_API_KEY"] is True
    assert status["DATABASE_URL"] is False
    assert "secret-123" not in repr(status)
