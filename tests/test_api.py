"""app.py and backend/api/: every route, offline, through FastAPI's TestClient."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fakes import FakeApollo, no_network_client, org, page
from fastapi.testclient import TestClient

from backend import db
from backend.app import create_app
from backend.pipeline import STAGES

LOCAL = "http://127.0.0.1"  # the app refuses any other Host


@pytest.fixture
def client(project: Path) -> Iterator[TestClient]:
    app = create_app(project, ui_dist=project / "no-ui")
    app.state.new_http_client = no_network_client
    with TestClient(app, base_url=LOCAL) as test_client:
        yield test_client


def add_companies(project: Path, count: int, segment: str = "ai_accounting") -> None:
    conn = db.connect(project)
    with conn:
        for i in range(1, count + 1):
            db.insert_company(
                conn,
                {
                    "domain": f"firm{i}.com",
                    "name": f"Firm {i}",
                    "source": "apollo",
                    "source_id": f"org{i}",
                    "segment": segment,
                },
            )
    conn.close()


def clay_file(rows: list[dict[str, str]]) -> bytes:
    headers = ["Company Domain", "First Name", "Work Email", "Validate Email", "Notes"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


CLAY_ROWS = [
    {"Company Domain": "firm1.com", "First Name": "Ann", "Work Email": "ann@firm1.com",
     "Validate Email": "valid"},
    {"Company Domain": "firm2.com", "First Name": "Bo", "Work Email": "bo@firm2.com",
     "Validate Email": "catch-all"},
    {"Company Domain": "firm3.com", "First Name": "", "Work Email": "info@firm3.com",
     "Validate Email": "valid"},
]  # fmt: skip


# --- overview -----------------------------------------------------------------------------------


def test_overview_follows_the_stage_list(client: TestClient) -> None:
    data = client.get("/api/overview").json()
    assert [s["key"] for s in data["stages"]] == [s.key for s in STAGES]
    assert [s["built"] for s in data["stages"]] == [s.built for s in STAGES]
    assert data["apollo"] == {"month": db.current_month(), "used": 0, "cap": 10}
    assert data["keys"] == {"APOLLO_API_KEY": False, "DATABASE_URL": data["keys"]["DATABASE_URL"]}
    assert data["companies"]["total"] == 0


def test_overview_counts_companies_and_leads(client: TestClient, project: Path) -> None:
    add_companies(project, 3)
    client.post("/api/clay/export", json={"rows": 3})
    client.post(
        "/api/clay/import",
        files={"file": ("clay.csv", clay_file(CLAY_ROWS))},
        data={"mapping": json.dumps({"domain": "Company Domain", "email": "Work Email",
                                     "email_status": "Validate Email"})},
    )  # fmt: skip
    data = client.get("/api/overview").json()
    enrich = next(s for s in data["stages"] if s["key"] == "enrich")
    counts = {w["state"]: w["count"] for w in enrich["writes"]}
    assert counts["verified"] == 1 and counts["needs_check"] == 1 and counts["hold"] == 1
    assert data["states"]["sourced"] == 3
    assert data["companies"]["by_status"] == {"enriched": 3}


def test_overview_shows_keys_as_set_never_their_values(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "secret-123")
    response = client.get("/api/overview")
    assert response.json()["keys"]["APOLLO_API_KEY"] is True
    assert "secret-123" not in response.text
    assert "postgresql" not in response.text


# --- segments and source ------------------------------------------------------------------------


def test_segments(client: TestClient, project: Path) -> None:
    add_companies(project, 2)
    data = client.get("/api/segments").json()
    by_key = {s["key"]: s for s in data}
    assert set(by_key) == {"ai_accounting", "frontend_agencies"}
    assert by_key["ai_accounting"]["saved"] == 2
    assert by_key["ai_accounting"]["waiting_for_clay"] == 2
    assert by_key["ai_accounting"]["keywords"] == ["accounting", "bookkeeping"]


def test_preview_is_free_and_offline(client: TestClient) -> None:
    response = client.post("/api/source/preview", json={"segment": "ai_accounting", "pages": 2})
    assert response.status_code == 200
    data = response.json()
    assert "pages:    1 to 2" in data["text"]
    assert data["credits"] == 2
    assert "APOLLO_API_KEY" in data["problem"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"segment": "nope", "pages": 1}, "No segment called"),
        ({"segment": "ai_accounting", "pages": 0}, "Pages must be between"),
        ({"segment": "ai_accounting", "pages": 51}, "Pages must be between"),
    ],
)
def test_preview_rejects_bad_input(client: TestClient, body: dict, message: str) -> None:
    response = client.post("/api/source/preview", json=body)
    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_run_needs_the_exact_credits_confirmed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    for confirm in (0, 1, 3):  # 2 pages can spend 2 credits
        response = client.post(
            "/api/source/run",
            json={"segment": "ai_accounting", "pages": 2, "confirm_credits": confirm},
        )
        assert response.status_code == 400
        assert "Spend up to 2 credits" in response.json()["detail"]
    assert client.get("/api/overview").json()["apollo"]["used"] == 0


def test_run_needs_a_key(client: TestClient) -> None:
    response = client.post(
        "/api/source/run", json={"segment": "ai_accounting", "pages": 1, "confirm_credits": 1}
    )
    assert response.status_code == 400
    assert "APOLLO_API_KEY isn't set" in response.json()["detail"]


def test_run_needs_a_cap(
    client: TestClient, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    (project / "config" / "settings.yaml").write_text("caps:\n  other:\n    x: 1\n")
    response = client.post(
        "/api/source/run", json={"segment": "ai_accounting", "pages": 1, "confirm_credits": 1}
    )
    assert response.status_code == 400
    assert "caps.apollo.credits" in response.json()["detail"]


def test_run_fetches_and_saves(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    fake = FakeApollo((200, page([org(1), org(2), org(3, domain="", website_url=None)])))
    client.app.state.new_http_client = fake.client
    response = client.post(
        "/api/source/run", json={"segment": "ai_accounting", "pages": 1, "confirm_credits": 1}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["saved"] == 2 and data["result"]["no_domain"] == 1
    assert data["used"] == 1 and data["cap"] == 10
    assert "saved (new)          2" in data["summary"]
    assert fake.pages_requested() == [1]
    assert client.get("/api/companies").json()["total"] == 2


def test_run_never_goes_over_the_cap(
    client: TestClient, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    conn = db.connect(project)
    with conn:
        db.add_usage(conn, "apollo", "credits", 10)
    conn.close()
    response = client.post(
        "/api/source/run", json={"segment": "ai_accounting", "pages": 1, "confirm_credits": 1}
    )
    assert response.status_code == 200  # no_network_client: any request would fail the test
    assert response.json()["result"]["stopped_by_cap"] is True
    assert response.json()["used"] == 10


# --- companies ----------------------------------------------------------------------------------


def test_companies_list_and_search(client: TestClient, project: Path) -> None:
    add_companies(project, 12)
    assert client.get("/api/companies").json()["total"] == 12
    found = client.get("/api/companies", params={"search": "FIRM1"}).json()
    assert sorted(r["domain"] for r in found["rows"]) == ["firm1.com", "firm10.com", "firm11.com",
                                                          "firm12.com"]  # fmt: skip
    assert (
        client.get("/api/companies", params={"segment": "frontend_agencies"}).json()["total"] == 0
    )
    assert client.get("/api/companies", params={"segment": "nope"}).status_code == 400


def test_companies_csv(client: TestClient, project: Path) -> None:
    add_companies(project, 2)
    response = client.get("/api/companies.csv", params={"search": "firm2"})
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"\xef\xbb\xbf")  # BOM, for Excel
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert [r["domain"] for r in rows] == ["firm2.com"]


# --- clay ---------------------------------------------------------------------------------------


def test_clay_export_and_download(client: TestClient, project: Path) -> None:
    add_companies(project, 3)
    response = client.post("/api/clay/export", json={"segment": "ai_accounting", "rows": 2})
    assert response.status_code == 200
    batch = response.json()
    assert batch["rows"] == 2
    file = client.get(f"/api/clay/batches/{batch['batch_id']}/file")
    assert file.status_code == 200
    rows = list(csv.DictReader(io.StringIO(file.text)))
    assert [r["domain"] for r in rows] == ["firm1.com", "firm2.com"]
    listed = client.get("/api/clay/batches").json()
    assert listed["waiting"] == 1
    assert listed["batches"][0]["rows"] == 2


def test_clay_export_with_nothing_waiting(client: TestClient) -> None:
    response = client.post("/api/clay/export", json={})
    assert response.status_code == 404
    assert "Nothing is waiting for Clay" in response.json()["detail"]


def test_clay_export_bad_input(client: TestClient) -> None:
    assert client.post("/api/clay/export", json={"rows": 0}).status_code == 400
    assert client.post("/api/clay/export", json={"segment": "nope"}).status_code == 400


def test_clay_download_unknown_batch(client: TestClient) -> None:
    assert client.get("/api/clay/batches/99/file").status_code == 404


def test_clay_columns_are_detected(client: TestClient) -> None:
    response = client.post("/api/clay/columns", files={"file": ("c.csv", clay_file(CLAY_ROWS))})
    data = response.json()
    assert data["rows"] == 3
    assert data["mapping"]["email"] == "Work Email"
    assert data["mapping"]["email_status"] == "Validate Email"
    assert data["mapping"]["title"] is None
    assert data["missing"] == []
    assert {"key": "email", "label": "Email"} in data["fields"]


def test_clay_columns_rejects_an_empty_file(client: TestClient) -> None:
    response = client.post("/api/clay/columns", files={"file": ("c.csv", b"")})
    assert response.status_code == 400


def test_clay_import(client: TestClient, project: Path) -> None:
    add_companies(project, 3)
    batch = client.post("/api/clay/export", json={"rows": 3}).json()
    mapping = {"domain": "Company Domain", "email": "Work Email", "email_status": "Validate Email",
               "first_name": "First Name", "title": ""}  # fmt: skip
    response = client.post(
        "/api/clay/import",
        files={"file": ("clay.csv", clay_file(CLAY_ROWS))},
        data={"mapping": json.dumps(mapping), "account": "clay-1", "credits": "12"},
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["saved"] == 3
    assert result["states"] == {"verified": 1, "needs_check": 1, "hold": 1}
    assert result["batches"] == [batch["batch_id"]]
    assert "cost: 12 Clay credits" in response.json()["summary"]
    row = client.get("/api/clay/batches").json()["batches"][0]
    assert row["clay_account"] == "clay-1" and row["verified"] == 1


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        ({"domain": "Company Domain"}, "Choose a column for: Email"),
        ({"email": "Work Email", "domain": "Missing"}, "no column called 'Missing'"),
        ({"email": "Work Email", "colour": "Notes"}, "Unknown field"),
    ],
)
def test_clay_import_rejects_a_bad_mapping(client: TestClient, mapping: dict, message: str) -> None:
    response = client.post(
        "/api/clay/import",
        files={"file": ("clay.csv", clay_file(CLAY_ROWS))},
        data={"mapping": json.dumps(mapping)},
    )
    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_clay_import_rejects_mapping_that_is_not_json(client: TestClient) -> None:
    response = client.post(
        "/api/clay/import",
        files={"file": ("clay.csv", clay_file(CLAY_ROWS))},
        data={"mapping": "email=Work Email"},
    )
    assert response.status_code == 400


# --- leads --------------------------------------------------------------------------------------


def test_leads_by_state_and_csv(client: TestClient, project: Path) -> None:
    add_companies(project, 3)
    client.post("/api/clay/export", json={"rows": 3})
    client.post(
        "/api/clay/import",
        files={"file": ("clay.csv", clay_file(CLAY_ROWS))},
        data={"mapping": json.dumps({"domain": "Company Domain", "email": "Work Email",
                                     "email_status": "Validate Email"})},
    )  # fmt: skip
    data = client.get("/api/leads").json()
    assert data["total"] == 3 and data["counts"]["verified"] == 1
    assert "needs_check" in data["states"]
    verified = client.get("/api/leads", params={"state": "verified"}).json()
    assert [r["email"] for r in verified["rows"]] == ["ann@firm1.com"]
    assert client.get("/api/leads", params={"state": "nope"}).status_code == 400
    response = client.get("/api/leads.csv", params={"state": "needs_check"})
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert [r["email"] for r in rows] == ["bo@firm2.com"]


# --- do-not-contact -----------------------------------------------------------------------------


def test_suppression_add_and_list(client: TestClient, project: Path) -> None:
    add_companies(project, 2)
    response = client.post(
        "/api/suppression", json={"value": "https://www.Firm1.com/", "reason": "client"}
    )
    assert response.json() == {"value": "firm1.com", "kind": "domain", "added": True}
    again = client.post("/api/suppression", json={"value": "firm1.com", "reason": "client"})
    assert again.json()["added"] is False
    listed = client.get("/api/suppression").json()
    assert [(r["value"], r["reason"]) for r in listed] == [("firm1.com", "client")]
    assert client.get("/api/companies").json()["total"] == 1  # hidden from the list


def test_suppression_rejects_bad_input(client: TestClient) -> None:
    assert client.post("/api/suppression", json={"value": "x", "reason": " "}).status_code == 400
    assert client.post("/api/suppression", json={"value": "@", "reason": "r"}).status_code == 400


def test_suppression_can_never_be_removed(client: TestClient) -> None:
    client.post("/api/suppression", json={"value": "acme.com", "reason": "client"})
    assert client.delete("/api/suppression").status_code == 405
    assert client.delete("/api/suppression/acme.com").status_code == 404
    assert len(client.get("/api/suppression").json()) == 1


# --- app ----------------------------------------------------------------------------------------


def test_other_websites_are_refused(client: TestClient) -> None:
    body = {"value": "acme.com", "reason": "r"}
    evil = client.post("/api/suppression", json=body, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    local = client.post("/api/suppression", json=body, headers={"Origin": "http://localhost:5173"})
    assert local.status_code == 200
    assert client.get("/api/overview", headers={"Host": "evil.example"}).status_code == 400


def test_errors_are_json(project: Path) -> None:
    app = create_app(project, ui_dist=project / "no-ui")
    (project / "config" / "settings.yaml").write_text("caps: 3\n")
    with TestClient(app, base_url=LOCAL, raise_server_exceptions=False) as test_client:
        response = test_client.get("/api/overview")
    assert response.status_code == 500
    assert response.json()["detail"].startswith("Config error:")


def test_unexpected_errors_are_json(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("backend.overview.overview", boom)
    app = create_app(project, ui_dist=project / "no-ui")
    with TestClient(app, base_url=LOCAL, raise_server_exceptions=False) as test_client:
        response = test_client.get("/api/overview")
    assert response.status_code == 500
    assert "RuntimeError" in response.json()["detail"]


def test_built_ui_is_served(project: Path) -> None:
    dist = project / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<h1>outbound</h1>", encoding="utf-8")
    with TestClient(create_app(project, ui_dist=dist), base_url=LOCAL) as test_client:
        assert "outbound" in test_client.get("/").text
        assert test_client.get("/api/segments").status_code == 200
