"""config.py: settings, segments and .env loading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from outbound.config import ConfigError, key_status, load_env, load_segments, load_settings


def write(project: Path, name: str, text: str) -> None:
    (project / "config" / name).write_text(text, encoding="utf-8")


def test_valid_settings_load(project: Path) -> None:
    settings = load_settings(project)
    assert settings.database == (project / "data" / "outbound.db").resolve()
    assert settings.caps == {"apollo": {"credits": 10}}


def test_missing_settings_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="settings.yaml"):
        load_settings(tmp_path)


def test_unknown_settings_key(project: Path) -> None:
    write(project, "settings.yaml", "database: x.db\ncaps: {apollo: {credits: 1}}\ndatabse: y\n")
    with pytest.raises(ConfigError, match="databse"):
        load_settings(project)


@pytest.mark.parametrize("value", ["-1", "ten", "true", "1.5"])
def test_bad_cap(project: Path, value: str) -> None:
    write(project, "settings.yaml", f"database: x.db\ncaps:\n  apollo:\n    credits: {value}\n")
    with pytest.raises(ConfigError, match="caps.apollo.credits"):
        load_settings(project)


def test_settings_not_a_mapping(project: Path) -> None:
    write(project, "settings.yaml", "- just\n- a list\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_settings(project)


def test_valid_segments_load(project: Path) -> None:
    segments = load_segments(project)
    assert sorted(segments) == ["ai_accounting", "frontend_agencies"]
    accounting = segments["ai_accounting"]
    assert accounting.offer == "ai_automation"
    assert accounting.keywords == ("accounting", "bookkeeping")
    assert accounting.max_employees == 20
    assert segments["frontend_agencies"].keywords == ()
    assert segments["frontend_agencies"].max_employees == 20


SEGMENT = """\
segments:
  {name}:
    offer: {offer}
    description: test
    employees: [{employees}]
    locations: ["United States"]
    keywords: ["x"]
{extra}"""


@pytest.mark.parametrize(
    ("name", "offer", "employees", "extra", "message"),
    [
        ("Bad-Name", "frontend", '"1,20"', "", "lowercase"),
        ("ok", "sales", '"1,20"', "", "offer"),
        ("ok", "frontend", '"20,1"', "", "min <= max"),
        ("ok", "frontend", '"1-20"', "", "1,20"),
        ("ok", "frontend", "", "", "must not be empty"),
        ("ok", "frontend", '"1,20"', "    pages: 3\n", "unknown key 'pages'"),
    ],
)
def test_bad_segments(
    project: Path, name: str, offer: str, employees: str, extra: str, message: str
) -> None:
    write(
        project,
        "segments.yaml",
        SEGMENT.format(name=name, offer=offer, employees=employees, extra=extra),
    )
    with pytest.raises(ConfigError, match=message):
        load_segments(project)


def test_segment_missing_field(project: Path) -> None:
    write(project, "segments.yaml", "segments:\n  ok:\n    offer: frontend\n")
    with pytest.raises(ConfigError, match="missing 'description'"):
        load_segments(project)


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
    status = key_status()
    assert status == {"APOLLO_API_KEY": True}
    assert "secret-123" not in repr(status)
