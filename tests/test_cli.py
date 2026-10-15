"""cli.py: every command, as you'd type it."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from fakes import FakeApollo, no_network_client, org, page

from outbound import cli


def call(project: Path, *args: str) -> int:
    return cli.main(["--root", str(project), *args])


def test_check(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert call(project, "check") == 0
    out = capsys.readouterr().out
    assert "config:   ok" in out
    assert "database: data/outbound.db" in out
    assert "APOLLO_API_KEY  not set" in out
    assert "apollo credits  0 / 10" in out
    assert "ai_accounting" in out and "0 saved" in out


def test_check_never_prints_the_key(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "secret-123")
    assert call(project, "check") == 0
    captured = capsys.readouterr()
    assert "APOLLO_API_KEY  set" in captured.out
    assert "secret-123" not in captured.out + captured.err


def test_key_is_read_from_dot_env(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (project / ".env").write_text("APOLLO_API_KEY=from-file\n", encoding="utf-8")
    call(project, "check")
    assert "APOLLO_API_KEY  set" in capsys.readouterr().out


def test_broken_config(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (project / "config" / "settings.yaml").write_text("caps: {}\n", encoding="utf-8")
    assert call(project, "check") == 2
    assert "config error" in capsys.readouterr().err


def test_source_dry_run_uses_no_network(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "new_client", no_network_client)
    monkeypatch.setenv("APOLLO_API_KEY", "key")
    assert call(project, "source", "ai_accounting", "--pages", "2") == 0
    assert "DRY RUN" in capsys.readouterr().out


def test_source_unknown_segment(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert call(project, "source", "nope") == 2
    assert "ai_accounting" in capsys.readouterr().err


def test_source_live_needs_a_key(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert call(project, "source", "ai_accounting", "--live") == 2
    assert "APOLLO_API_KEY" in capsys.readouterr().err


def test_source_rejects_silly_page_counts(project: Path) -> None:
    assert call(project, "source", "ai_accounting", "--pages", "0") == 2


def test_source_live_then_export(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeApollo((200, page([org(1), org(2), org(3, "", website_url=None)])))
    monkeypatch.setattr(cli, "new_client", fake.client)
    monkeypatch.setenv("APOLLO_API_KEY", "key")
    assert call(project, "source", "ai_accounting", "--live") == 0
    out = capsys.readouterr().out
    assert "saved (new)          2" in out
    assert "(1 of 10 used this month)" in out

    assert call(project, "suppress", "company2.com", "--reason", "existing client") == 0
    target = project / "out.csv"
    assert call(project, "export", "--out", str(target)) == 0
    assert "wrote 1 companies" in capsys.readouterr().out
    with target.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["domain"] for row in rows] == ["company1.com"]
    assert rows[0]["segment"] == "ai_accounting"


def test_source_live_reports_errors(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeApollo((403, {"error": "not on your plan"}))
    monkeypatch.setattr(cli, "new_client", fake.client)
    monkeypatch.setenv("APOLLO_API_KEY", "key")
    assert call(project, "source", "ai_accounting", "--live") == 1
    assert "refused Organization Search" in capsys.readouterr().out


def test_export_default_path(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert call(project, "export") == 0
    files = list((project / "data" / "exports").glob("companies_*.csv"))
    assert len(files) == 1


def test_suppress(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert call(project, "suppress", "https://www.Acme.com", "--reason", "client") == 0
    assert "added: domain acme.com" in capsys.readouterr().out
    assert call(project, "suppress", "acme.com", "--reason", "again") == 0
    assert "already on the list" in capsys.readouterr().out
    assert call(project, "suppress", "Jane@Acme.com", "--reason", "asked") == 0
    assert "added: email jane@acme.com" in capsys.readouterr().out
    assert call(project, "suppress", "not valid", "--reason", "x") == 2


def test_fields_lists_names_never_values(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert call(project, "fields") == 0
    assert "No saved companies yet" in capsys.readouterr().out

    records = [org(1, phone="555-0100-unique"), org(2, phone=None)]
    monkeypatch.setattr(cli, "new_client", FakeApollo((200, page(records))).client)
    monkeypatch.setenv("APOLLO_API_KEY", "key")
    call(project, "source", "ai_accounting", "--live")
    capsys.readouterr()

    assert call(project, "fields") == 0
    out = capsys.readouterr().out
    assert "Fields in 2 saved records" in out
    assert any(line.split() == ["phone", "1"] for line in out.splitlines())
    assert any(line.split() == ["primary_domain", "2"] for line in out.splitlines())
    assert "555-0100-unique" not in out
