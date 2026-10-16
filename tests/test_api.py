"""app.py and backend/api/: every route, offline, through FastAPI's TestClient."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fakes import (
    FakeApollo,
    icp_data,
    maps_settings,
    no_network_client,
    org,
    page,
    place,
    places_page,
)
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


def add_companies(project: Path, count: int, icp: str = "bpa_us_recruit") -> None:
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
                    "icp": icp,
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
    assert (
        data["keys"]["APOLLO_API_KEY"] is False and data["keys"]["GOOGLE_PLACES_API_KEY"] is False
    )
    assert [(u["source"], u["used"], u["cap"]) for u in data["usage"]] == [
        ("apollo", 0, 10),
        ("google_maps", 0, 5),
    ]
    assert data["companies"]["total"] == 0


def test_overview_counts_companies_and_leads(client: TestClient, project: Path) -> None:
    add_companies(project, 3)
    client.post("/api/clay/export", json={"icp": ICP, "rows": 3})
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


# --- ICPs and sources ---------------------------------------------------------------------------

ICP = "bpa_us_recruit"  # a starting ICP that is active and has no job-post signal


def test_sources_list_every_source_with_its_fields(client: TestClient) -> None:
    data = {s["key"]: s for s in client.get("/api/sources").json()}
    assert data["apollo"]["built"] is True and data["google_maps"]["built"] is True
    assert data["google_maps"]["provider"] == "google_places"
    assert [f["key"] for f in data["google_maps"]["fields"]] == [
        "queries", "cities", "region_code", "place_type", "pages_per_query", "skip_chains",
    ]  # fmt: skip


def test_icps_list_with_counts(client: TestClient, project: Path) -> None:
    add_companies(project, 2)
    rows = client.get("/api/icps").json()
    by_key = {r["key"]: r for r in rows}
    assert rows[0]["active"] is True and rows[-1]["active"] is False  # active first
    assert (by_key[ICP]["saved"], by_key[ICP]["waiting_for_clay"]) == (2, 2)
    assert by_key[ICP]["sources"]["apollo"]["hq_locations"] == ["Texas", "Florida"]


def test_icp_create_edit_deactivate(client: TestClient) -> None:
    created = client.post("/api/icps", json=icp_data("vets_us"))
    assert created.status_code == 200 and created.json()["key"] == "vets_us"
    again = client.post("/api/icps", json=icp_data("vets_us"))
    assert again.status_code == 400 and "already an ICP" in again.json()["detail"]

    changed = client.put("/api/icps/vets_us", json=icp_data("vets_us", name="US vets"))
    assert changed.json()["name"] == "US vets"
    assert client.get("/api/icps/vets_us").json()["name"] == "US vets"

    off = client.post("/api/icps/vets_us/active", json={"active": False})
    assert off.json()["active"] is False
    assert client.put("/api/icps/nope", json=icp_data("nope")).status_code == 404
    assert client.get("/api/icps/nope").status_code == 404


def test_icp_errors_are_plain_sentences(client: TestClient) -> None:
    bad = icp_data(sources={"apollo": {"hq_locations": ["Texas"], "employee_ranges": ["1-10"]}})
    response = client.post("/api/icps", json=bad)
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == 'Apollo: Headcount ranges: "1-10" must look like "1,10" (smallest, largest)'
    )


def test_icps_are_never_deleted(client: TestClient) -> None:
    assert client.delete(f"/api/icps/{ICP}").status_code == 405


def test_preview_is_free_and_offline(client: TestClient) -> None:
    response = client.post("/api/source/preview", json={"icp": ICP, "pages": 2})
    assert response.status_code == 200
    data = response.json()
    [apollo_preview] = data["previews"]
    assert apollo_preview["credits"] == 2
    assert apollo_preview["confirm_label"] == "Spend up to 2 Apollo credits"
    assert "pages:    1 to 2" in apollo_preview["text"]
    assert "organization_locations[] = Texas" in apollo_preview["text"]
    assert "APOLLO_API_KEY" in apollo_preview["problem"]


def test_preview_shows_why_a_source_or_icp_cant_run(client: TestClient) -> None:
    data = client.post(
        "/api/source/preview", json={"icp": ICP, "sources": ["apollo", "google_maps"]}
    ).json()
    maps = data["previews"][1]
    assert "has no Google Maps settings" in maps["problem"] and maps["credits"] == 0
    signal = client.post("/api/source/preview", json={"icp": "dev_us_signal"}).json()
    assert "job-post signal" in signal["previews"][0]["problem"]
    assert "NOT SENT" in signal["previews"][0]["text"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"icp": "nope", "pages": 1}, 'No ICP called "nope"'),
        ({"icp": ICP, "pages": 0}, "Pages must be between"),
        ({"icp": ICP, "pages": 51}, "Pages must be between"),
        ({"icp": ICP, "sources": []}, "Pick at least one source"),
        ({"icp": ICP, "sources": ["yelp"]}, "No source called 'yelp'"),
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
            "/api/source/run", json={"icp": ICP, "pages": 2, "confirm": {"apollo": confirm}}
        )
        assert response.status_code == 400
        assert "Spend up to 2 Apollo credits" in response.json()["detail"]
    assert client.get("/api/overview").json()["apollo"]["used"] == 0


def test_run_needs_a_key(client: TestClient) -> None:
    response = client.post(
        "/api/source/run", json={"icp": ICP, "pages": 1, "confirm": {"apollo": 1}}
    )
    assert response.status_code == 400
    assert "APOLLO_API_KEY isn't set" in response.json()["detail"]


def test_run_needs_a_cap(
    client: TestClient, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    (project / "config" / "settings.yaml").write_text("caps:\n  other:\n    x: 1\n")
    response = client.post(
        "/api/source/run", json={"icp": ICP, "pages": 1, "confirm": {"apollo": 1}}
    )
    assert response.status_code == 400
    assert "caps.apollo.credits" in response.json()["detail"]


def test_run_checks_every_source_before_spending(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    response = client.post(
        "/api/source/run",
        json={"icp": ICP, "sources": ["apollo", "google_maps"], "pages": 1,
              "confirm": {"apollo": 1, "google_maps": 0}},
    )  # fmt: skip
    assert response.status_code == 400
    assert "has no Google Maps settings" in response.json()["detail"]
    assert client.get("/api/overview").json()["apollo"]["used"] == 0


def test_run_refuses_an_inactive_icp(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    response = client.post(
        "/api/source/run", json={"icp": "ai_accounting", "pages": 1, "confirm": {"apollo": 1}}
    )
    assert response.status_code == 400 and "inactive" in response.json()["detail"]


def test_run_fetches_and_saves(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    fake = FakeApollo((200, page([org(1), org(2), org(3, domain="", website_url=None)])))
    client.app.state.new_http_client = fake.client
    response = client.post(
        "/api/source/run", json={"icp": ICP, "pages": 1, "confirm": {"apollo": 1}}
    )
    assert response.status_code == 200
    [run] = response.json()["runs"]
    assert run["result"]["saved"] == 2 and run["result"]["no_domain"] == 1
    assert run["used"] == 1 and run["cap"] == 10
    assert "saved (new)          2" in run["summary"]
    assert "Apollo reports about 500 matching companies" in run["summary"]
    assert fake.pages_requested() == [1]
    assert fake.requests[0].url.params.get_list("organization_locations[]") == ["Texas", "Florida"]
    rows = client.get("/api/companies", params={"icp": ICP}).json()["rows"]
    assert {r["icp"] for r in rows} == {ICP} and len(rows) == 2


def test_run_never_goes_over_the_cap(
    client: TestClient, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    conn = db.connect(project)
    with conn:
        db.add_usage(conn, "apollo", "credits", 10)
    conn.close()
    response = client.post(
        "/api/source/run", json={"icp": ICP, "pages": 1, "confirm": {"apollo": 1}}
    )
    assert response.status_code == 200  # no_network_client: any request would fail the test
    [run] = response.json()["runs"]
    assert run["result"]["stopped_by_cap"] is True and run["used"] == 10


def _maps_icp(client: TestClient) -> None:
    body = icp_data("vets_us", sources={"apollo": icp_data()["sources"]["apollo"],
                                         "google_maps": maps_settings(queries=["vets", "vet clinic"])})  # fmt: skip
    assert client.post("/api/icps", json=body).status_code == 200


def test_google_preview_lists_searches_and_its_own_confirm(client: TestClient) -> None:
    _maps_icp(client)
    data = client.post(
        "/api/source/preview", json={"icp": "vets_us", "sources": ["google_maps", "apollo"]}
    ).json()
    assert [p["source"] for p in data["previews"]] == ["apollo", "google_maps"]  # Apollo first
    maps = data["previews"][1]
    assert maps["credits"] == 2
    assert maps["confirm_label"] == "Spend up to 2 Google Maps requests (free up to 1,000 a month)"
    assert "vets in Austin, TX  ->  1 request(s)" in maps["text"]
    assert "GOOGLE_PLACES_API_KEY" in maps["problem"]


def test_both_sources_run_apollo_then_google_each_confirmed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _maps_icp(client)
    monkeypatch.setenv("APOLLO_API_KEY", "a-key")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "g-key")
    body = {"icp": "vets_us", "sources": ["apollo", "google_maps"], "pages": 1}
    missing = client.post("/api/source/run", json={**body, "confirm": {"apollo": 1}})
    assert missing.status_code == 400
    assert "Spend up to 2 Google Maps requests" in missing.json()["detail"]

    fake = FakeApollo(
        (200, page([org(1)])),
        (200, places_page([place(1, website="https://company1.com"), place(2)])),
        (200, places_page([place(3, businessStatus="CLOSED_TEMPORARILY")])),
    )
    client.app.state.new_http_client = fake.client
    response = client.post(
        "/api/source/run", json={**body, "confirm": {"apollo": 1, "google_maps": 2}}
    )
    assert response.status_code == 200
    apollo_run, maps_run = response.json()["runs"]
    assert (apollo_run["source"], maps_run["source"]) == ("apollo", "google_maps")
    assert fake.requests[0].url.host == "api.apollo.io"
    assert {r.url.host for r in fake.requests[1:]} == {"places.googleapis.com"}
    assert fake.requests[1].headers["X-Goog-Api-Key"] == "g-key"
    result = maps_run["result"]
    assert (result["saved"], result["duplicate"], result["closed"]) == (1, 1, 1)
    assert (maps_run["used"], maps_run["cap"]) == (2, 5)
    usage = {u["source"]: u["used"] for u in client.get("/api/overview").json()["usage"]}
    assert usage == {"apollo": 1, "google_maps": 2}

    rows = client.get("/api/companies", params={"source": "google_places"}).json()["rows"]
    assert [(r["domain"], r["city"], r["state"], r["likely_chain"]) for r in rows] == [
        ("clinic2.com", "Austin", "TX", 0)
    ]
    assert client.get("/api/companies", params={"source": "apollo"}).json()["total"] == 1


# --- companies ----------------------------------------------------------------------------------


def test_companies_list_and_search(client: TestClient, project: Path) -> None:
    add_companies(project, 12)
    assert client.get("/api/companies").json()["total"] == 12
    found = client.get("/api/companies", params={"search": "FIRM1"}).json()
    assert sorted(r["domain"] for r in found["rows"]) == ["firm1.com", "firm10.com", "firm11.com",
                                                          "firm12.com"]  # fmt: skip
    assert client.get("/api/companies", params={"icp": "dev_us_pain"}).json()["total"] == 0
    assert client.get("/api/companies", params={"icp": "nope"}).status_code == 400


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
    response = client.post("/api/clay/export", json={"icp": ICP, "rows": 2})
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
    response = client.post("/api/clay/export", json={"icp": ICP})
    assert response.status_code == 404
    assert "Nothing from bpa_us_recruit is waiting for Clay" in response.json()["detail"]


def test_clay_export_bad_input(client: TestClient) -> None:
    assert client.post("/api/clay/export", json={"icp": ICP, "rows": 0}).status_code == 400
    assert client.post("/api/clay/export", json={"icp": "nope"}).status_code == 400
    assert client.post("/api/clay/export", json={"rows": 5}).status_code == 422  # ICP required


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
    batch = client.post("/api/clay/export", json={"icp": ICP, "rows": 3}).json()
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
    client.post("/api/clay/export", json={"icp": ICP, "rows": 3})
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
        assert test_client.get("/api/icps").status_code == 200
