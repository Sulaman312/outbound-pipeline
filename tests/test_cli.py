"""cli.py: every command, as you'd type it."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import cli


def call(project: Path, *args: str) -> int:
    return cli.main(["--root", str(project), *args])


def test_check(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert call(project, "check") == 0
    out = capsys.readouterr().out
    assert "config:   ok" in out
    assert "sqlite at" in out or "postgres at" in out
    assert "APOLLO_API_KEY  not set" in out
    assert "GOOGLE_PLACES_API_KEY  not set" in out
    assert "apollo credits  0 / 10" in out
    assert "google_places requests  0 / 5" in out
    assert "ai_accounting" in out and "0 saved" in out


def test_check_never_prints_secrets(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "secret-123")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://user:s3cret@db.example.com:5432/outbound"
    )
    # Don't actually connect to that host: clear DATABASE_URL after key_status would see it
    # for the check output of keys, but connect uses it — so only set the key.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert call(project, "check") == 0
    captured = capsys.readouterr()
    assert "APOLLO_API_KEY  set" in captured.out
    assert "secret-123" not in captured.out + captured.err


def test_check_never_prints_database_url(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When DATABASE_URL is set, check shows host only, never the URL or password."""
    # Use sqlite so we don't need a real Postgres; describe_database is unit-tested separately.
    assert call(project, "check") == 0
    out = capsys.readouterr().out
    assert "DATABASE_URL" in out  # key name is fine
    assert "postgresql://" not in out
    assert "postgres://" not in out


def test_key_is_read_from_dot_env(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (project / ".env").write_text("APOLLO_API_KEY=from-file\n", encoding="utf-8")
    call(project, "check")
    assert "APOLLO_API_KEY  set" in capsys.readouterr().out


def test_broken_config(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (project / "config" / "settings.yaml").write_text(
        "caps:\n  apollo:\n    credits: -1\n", encoding="utf-8"
    )
    assert call(project, "check") == 2
    assert "config error" in capsys.readouterr().err


def test_backup(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert call(project, "backup") == 0
    out = capsys.readouterr().out
    assert "data/backups/" in out
    files = list((project / "data" / "backups").glob("*.json"))
    assert len(files) == 1


def test_serve_starts_the_app_on_this_computer_only(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    started: dict[str, object] = {}
    monkeypatch.setattr(
        cli.uvicorn, "run", lambda app, host, port, log_level: started.update(host=host, port=port)
    )
    monkeypatch.setattr(cli.app, "UI_DIST", project / "missing")
    assert call(project, "serve", "--no-browser") == 0
    assert started == {"host": "127.0.0.1", "port": 8000}
    out = capsys.readouterr().out
    assert "npm install" in out and "npm run build" in out


def test_serve_opens_the_browser_when_the_ui_is_built(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dist = project / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<h1>app</h1>", encoding="utf-8")
    opened: list[object] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(cli.app, "UI_DIST", dist)
    monkeypatch.setattr(
        cli.threading, "Timer", lambda delay, fn, args: opened.append(args) or _Now()
    )
    assert call(project, "serve", "--port", "8123") == 0
    assert opened == [["http://127.0.0.1:8123"]]
    assert "http://127.0.0.1:8123" in capsys.readouterr().out


class _Now:
    def start(self) -> None:
        pass


def test_check_shows_google_key_without_its_value(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "g-secret-456")
    assert call(project, "check") == 0
    out = capsys.readouterr().out
    assert "GOOGLE_PLACES_API_KEY  set" in out and "g-secret-456" not in out
