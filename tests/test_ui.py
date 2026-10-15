"""ui.py and `outbound ui`: the web page, clicked through headlessly with a fake Apollo."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeApollo, org, page

from outbound import cli, db, http

streamlit_testing = pytest.importorskip("streamlit.testing.v1")

UI_FILE = str(Path(cli.__file__).with_name("ui.py"))


@pytest.fixture
def app(project: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OUTBOUND_ROOT", str(project))
    return streamlit_testing.AppTest.from_file(UI_FILE, default_timeout=30)


def saved_domains(project: Path) -> list[str]:
    conn = db.connect(project / "data" / "outbound.db")
    try:
        return sorted(row["domain"] for row in db.list_companies(conn))
    finally:
        conn.close()


def test_page_loads_with_overview(app) -> None:
    app.run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Overview",
        "Find companies",
        "Companies",
        "Do-not-contact",
    ]
    assert app.metric[0].value == "0 / 10"
    assert any("APOLLO_API_KEY isn't set" in w.value for w in app.warning)


def test_config_error_is_shown(app, project: Path) -> None:
    (project / "config" / "settings.yaml").write_text("caps: {}\n", encoding="utf-8")
    app.run()
    assert "Config error" in app.error[0].value


def test_preview_is_free_and_fetch_needs_a_key(app) -> None:
    app.run()
    assert "cost:     up to 1 Apollo credit(s)" in app.code[0].value
    assert "--live" not in app.code[0].value
    assert app.button(key="find_run").disabled


def test_fetch_saves_companies(app, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "key")
    fake = FakeApollo((200, page([org(1), org(2)])))
    monkeypatch.setattr(http, "new_client", fake.client)
    app.run()
    assert app.button(key="find_run").disabled  # not until the spend box is ticked
    app.checkbox(key="find_confirm").check().run()
    app.button(key="find_run").click().run()

    assert not app.exception
    assert fake.pages_requested() == [1]
    assert saved_domains(project) == ["company1.com", "company2.com"]
    assert "saved (new)          2" in app.code[-1].value
    assert app.checkbox(key="find_confirm").value is False  # asks again before the next spend


def test_companies_table_and_search(app, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "key")
    monkeypatch.setattr(http, "new_client", FakeApollo((200, page([org(1), org(2)]))).client)
    app.run()
    app.checkbox(key="find_confirm").check().run()
    app.button(key="find_run").click().run()

    app.text_input(key="companies_search").input("company2").run()
    assert any("1 companies" in c.value for c in app.caption)


def test_do_not_contact_form(app, project: Path) -> None:
    app.run()
    app.text_input(key="suppress_value").input("https://www.Acme.com")
    app.text_input(key="suppress_reason").input("existing client")
    next(b for b in app.button if b.label == "Add to the do-not-contact list").click().run()
    assert "Added domain acme.com." in app.success[0].value

    conn = db.connect(project / "data" / "outbound.db")
    assert db.is_suppressed(conn, "acme.com")
    conn.close()


def test_ui_command_starts_streamlit_on_localhost(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: dict[str, object] = {}

    class FakeProcess:
        def __init__(self, command: list[str], env: dict[str, str]) -> None:
            started.update(command=command, env=env)

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(cli.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: started.update(url=url))

    assert cli.main(["--root", str(project), "ui"]) == 0
    command = started["command"]
    assert "--server.address=localhost" in command
    assert "--browser.gatherUsageStats=false" in command
    assert started["env"]["OUTBOUND_ROOT"] == str(project.resolve())
    assert started["url"] == cli.UI_URL


def test_ui_command_without_streamlit(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: None)
    assert cli.main(["--root", str(project), "ui"]) == 2
    assert 'pip install -e ".[ui]"' in capsys.readouterr().err
