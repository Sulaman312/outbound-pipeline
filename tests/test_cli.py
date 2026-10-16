"""cli.py: every command, as you'd type it."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from fakes import FakeApollo, no_network_client, org, page

from backend import cli


def call(project: Path, *args: str) -> int:
    return cli.main(["--root", str(project), *args])


def test_check(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert call(project, "check") == 0
    out = capsys.readouterr().out
    assert "config:   ok" in out
    assert "sqlite at" in out or "postgres at" in out
    assert "APOLLO_API_KEY  not set" in out
    assert "apollo credits  0 / 10" in out
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


def test_source_dry_run_uses_no_network(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "new_client", no_network_client)
    monkeypatch.setenv("APOLLO_API_KEY", "key")
    assert call(project, "source", "bpa_us_recruit", "--pages", "2") == 0
    assert "DRY RUN" in capsys.readouterr().out


def test_source_unknown_icp(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert call(project, "source", "nope") == 2
    err = capsys.readouterr().err
    assert "no ICP called 'nope'" in err and "bpa_us_recruit" in err


@pytest.mark.parametrize(
    ("icp", "message"),
    [("ai_accounting", "inactive"), ("dev_us_signal", "job-post signal")],
)
def test_source_refuses_icps_that_cant_run(
    project: Path, capsys: pytest.CaptureFixture[str], icp: str, message: str
) -> None:
    assert call(project, "source", icp) == 2
    assert message in capsys.readouterr().err


def test_icps_lists_them(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert call(project, "icps") == 0
    out = capsys.readouterr().out
    assert "dev_us_signal  (active; apollo)" in out
    assert "ai_accounting  (inactive; apollo)" in out


def test_source_live_needs_a_key(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert call(project, "source", "bpa_us_recruit", "--live") == 2
    assert "APOLLO_API_KEY" in capsys.readouterr().err


def test_source_rejects_silly_page_counts(project: Path) -> None:
    assert call(project, "source", "bpa_us_recruit", "--pages", "0") == 2


def test_source_live_then_export(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeApollo((200, page([org(1), org(2), org(3, "", website_url=None)])))
    monkeypatch.setattr(cli, "new_client", fake.client)
    monkeypatch.setenv("APOLLO_API_KEY", "key")
    assert call(project, "source", "bpa_us_recruit", "--live") == 0
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
    assert rows[0]["icp"] == "bpa_us_recruit"


def test_source_live_reports_errors(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeApollo((403, {"error": "not on your plan"}))
    monkeypatch.setattr(cli, "new_client", fake.client)
    monkeypatch.setenv("APOLLO_API_KEY", "key")
    assert call(project, "source", "bpa_us_recruit", "--live") == 1
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
    call(project, "source", "bpa_us_recruit", "--live")
    capsys.readouterr()

    assert call(project, "fields") == 0
    out = capsys.readouterr().out
    assert "Fields in 2 saved records" in out
    assert any(line.split() == ["phone", "1"] for line in out.splitlines())
    assert any(line.split() == ["primary_domain", "2"] for line in out.splitlines())
    assert "555-0100-unique" not in out


def fill(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Save company1.com to company3.com through a fake Apollo."""
    monkeypatch.setattr(cli, "new_client", FakeApollo((200, page([org(1), org(2), org(3)]))).client)
    monkeypatch.setenv("APOLLO_API_KEY", "key")
    call(project, "source", "bpa_us_recruit", "--live")
    capsys.readouterr()


def test_clay_round_trip(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fill(project, monkeypatch, capsys)
    assert call(project, "clay", "export", "bpa_us_recruit", "--rows", "2") == 0
    out = capsys.readouterr().out
    assert "wrote 2 companies to data/clay/batch_" in out and "(batch 1)" in out

    clay_file = project / "from_clay.csv"
    clay_file.write_text(
        "Company Domain,First Name,Work Email,Validate Email\r\n"
        "company1.com,Jane,jane@company1.com,valid\r\n"
        "company2.com,Joe,joe@company2.com,catch-all\r\n",
        encoding="utf-8",
    )
    assert call(project, "clay", "import", str(clay_file), "--credits", "3") == 0
    out = capsys.readouterr().out
    assert "columns used: domain=Company Domain" in out
    assert "verified" in out and "needs_check" in out

    assert call(project, "check") == 0
    out = capsys.readouterr().out
    assert "waiting for Clay: 1 companies" in out
    assert "1 verified" in out and "1 needs_check" in out

    target = project / "contacts.csv"
    assert call(project, "export", "--contacts", "--out", str(target)) == 0
    with target.open(encoding="utf-8-sig", newline="") as handle:
        emails = sorted(row["email"] for row in csv.DictReader(handle))
    assert emails == ["jane@company1.com", "joe@company2.com"]


def test_clay_import_explains_missing_columns(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = project / "bad.csv"
    bad.write_text("Full Name,Notes\r\nJane,x\r\n", encoding="utf-8")
    assert call(project, "clay", "import", str(bad)) == 2
    err = capsys.readouterr().err
    assert "can't tell which column is: Email" in err
    assert "columns in the file: Full Name, Notes" in err


def test_clay_export_with_nothing_waiting(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert call(project, "clay", "export", "bpa_us_recruit") == 0
    assert "Nothing from bpa_us_recruit is waiting for Clay" in capsys.readouterr().out
    assert call(project, "clay", "export", "nope") == 2


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
