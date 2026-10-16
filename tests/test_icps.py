"""icps.py and schema version 2: checking ICPs, saving them, and the move from segments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fakes import icp_data
from sqlalchemy import create_engine

from backend import db, icps, seed_icps
from backend.db import Connection


@pytest.fixture
def conn(project: Path) -> Connection:
    connection = db.connect(project)
    yield connection
    connection.close()


# --- checking -----------------------------------------------------------------------------------


def test_check_cleans_values() -> None:
    icp = icps.check(
        icp_data(
            key="Vets_US",
            name="  US vet clinics ",
            person_titles="Owner\n\nPractice Manager\nOwner\n",
            sources={
                "apollo": {
                    "hq_locations": ["Texas", " Florida "],
                    "employee_ranges": [" 1 , 10 "],
                    "keywords": [],
                    "job_posted_within_days": "",
                },
                "google_maps": {"queries": [], "cities": []},
            },
        )
    )
    assert icp.key == "vets_us"
    assert icp.name == "US vet clinics"
    assert icp.person_titles == ["Owner", "Practice Manager"]
    assert icp.sources == {
        "apollo": {"hq_locations": ["Texas", "Florida"], "employee_ranges": ["1,10"]}
    }  # empty fields and unused sources are left out


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"key": "Bad Key!"}, "Key must be"),
        ({"key": "x"}, "Key must be"),
        ({"name": " "}, "Name can't be empty"),
        ({"target_leads": -1}, "Target leads must be a whole number"),
        ({"target_leads": "many"}, "Target leads must be a whole number"),
        ({"active": "yes"}, "Active must be yes or no"),
        ({"person_titles": [1, 2]}, "list of text values"),
        ({"sources": {"apollo": {"hq_locations": ["US"], "employee_ranges": ["1-10"]}}}, 'must look like "1,10"'),
        ({"sources": {"apollo": {"hq_locations": ["US"], "employee_ranges": ["20,1"]}}}, "not above the second"),
        ({"sources": {"apollo": {"hq_locations": ["US"], "employee_ranges": ["0,10"]}}}, "1 or more"),
        ({"sources": {"apollo": {"keywords": ["saas"]}}}, "Company HQ locations can't be empty"),
        ({"sources": {"apollo": {"pages": 3}}}, "no setting called 'pages'"),
        ({"sources": {"yelp": {}}}, "no source called 'yelp'"),
        ({"sources": {"apollo": {"hq_locations": ["US"], "employee_ranges": ["1,10"],
                                 "job_posted_within_days": "soon"}}}, "whole number"),
    ],
)  # fmt: skip
def test_check_rejects_with_plain_messages(change: dict[str, Any], message: str) -> None:
    with pytest.raises(icps.IcpError, match=message):
        icps.check(icp_data(**change))


def test_google_maps_settings_get_defaults_and_checks() -> None:
    icp = icps.check(icp_data(sources={"google_maps": {"queries": "vet clinic\nanimal hospital",
                                                        "cities": ["Austin, TX"]}}))  # fmt: skip
    assert icp.sources == {
        "google_maps": {
            "queries": ["vet clinic", "animal hospital"],
            "cities": ["Austin, TX"],
            "region_code": "us",
            "pages_per_query": 1,
            "skip_chains": True,
        }
    }
    # defaults alone (as the form sends them) don't count as using Google Maps
    unused = icps.check(icp_data(sources={"google_maps": {"region_code": "us", "skip_chains": True,
                                                          "pages_per_query": 1, "queries": []}}))  # fmt: skip
    assert unused.sources == {}


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"queries": ["vets"]}, "Cities can't be empty"),
        ({"queries": ["vets"], "cities": ["Austin"], "pages_per_query": 4}, "from 1 to 3"),
        ({"queries": ["vets"], "cities": ["Austin"], "region_code": "usa"}, "two letters"),
        ({"queries": ["vets"], "cities": ["Austin"], "place_type": "Vet Care"}, "joined by _"),
        ({"queries": ["vets"], "cities": ["Austin"], "skip_chains": "no"}, "yes or no"),
    ],
)
def test_google_maps_settings_are_checked(settings: dict[str, Any], message: str) -> None:
    with pytest.raises(icps.IcpError, match=message):
        icps.check(icp_data(sources={"google_maps": settings}))


def test_every_seed_icp_passes_the_checks() -> None:
    for data in (*seed_icps.LEGACY_SEGMENTS, *seed_icps.PILOT_ICPS):
        assert icps.check(data).key == data["key"]


# --- saving -------------------------------------------------------------------------------------


def test_create_update_deactivate(conn: Connection) -> None:
    created = icps.create(conn, icp_data("vets_us", name="US vet clinics"))
    assert icps.get(conn, "vets_us") == created
    with pytest.raises(icps.IcpError, match="already an ICP"):
        icps.create(conn, icp_data("vets_us"))

    updated = icps.update(conn, "vets_us", icp_data("ignored", name="Vets", sources={}))
    assert updated.key == "vets_us" and updated.name == "Vets"
    assert icps.get(conn, "vets_us").sources == {}  # cleared settings are removed

    assert icps.set_active(conn, "vets_us", False).active is False
    assert icps.get(conn, "vets_us").active is False
    with pytest.raises(LookupError):
        icps.update(conn, "nope", icp_data())


def test_list_puts_active_first_with_counts(conn: Connection) -> None:
    icps.create(conn, icp_data("vets_us"))
    with conn:
        db.insert_company(conn, {"domain": "vet.com", "name": "Vet", "source": "apollo",
                                 "source_id": "v1", "icp": "vets_us"})  # fmt: skip
    rows = icps.summaries(conn)
    actives = [row["active"] for row in rows]
    assert actives == sorted(actives, reverse=True)
    vets = next(row for row in rows if row["key"] == "vets_us")
    assert (vets["saved"], vets["waiting_for_clay"]) == (1, 1)


# --- the database starts with ICPs, and old databases move over ---------------------------------


def test_new_database_has_the_starting_icps(conn: Connection) -> None:
    by_key = {icp.key: icp for icp in icps.list_all(conn)}
    assert {"dev_us_signal", "dev_us_pain", "bpa_us_recruit"} <= set(by_key)
    assert all(by_key[k].active for k in ("dev_us_signal", "dev_us_pain", "bpa_us_recruit"))
    assert not by_key["ai_accounting"].active
    assert by_key["bpa_us_recruit"].sources["apollo"]["employee_ranges"] == ["11,50"]
    assert by_key["dev_us_signal"].sources["apollo"]["job_posted_within_days"] == 60
    assert "job_titles" not in by_key["dev_us_pain"].sources["apollo"]
    assert by_key["bpa_us_recruit"].person_locations == ["Texas", "Florida"]


def _version_1_database(conn: Connection) -> None:
    """Build what Supabase holds today: schema version 1 with companies and progress."""
    for statement in db._schema_statements(conn.dialect):
        conn.execute(statement)
    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    for i in range(1, 4):
        conn.execute(
            "INSERT INTO companies (domain, name, source, source_id, segment, created_at) "
            "VALUES (:d, :n, 'apollo', :s, :seg, '2026-10-15T00:00:00Z')",
            {"d": f"firm{i}.com", "n": f"Firm {i}", "s": f"org{i}",
             "seg": "ai_accounting" if i < 3 else "old_thing"},
        )  # fmt: skip
    conn.execute(
        "INSERT INTO batches (file, rows, segment, exported_at) "
        "VALUES ('data/clay/b.csv', 1, 'ai_accounting', '2026-10-15T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO sourcing_progress (segment, filters_hash, next_page, total_entries, "
        "exhausted, updated_at) VALUES ('ai_accounting', 'h', 2, 900, 0, '2026-10-15T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO usage (provider, unit, month, amount) VALUES ('apollo', 'credits', '2026-10', 1)"
    )


@pytest.fixture
def old_url(tmp_path: Path) -> str:
    """A database at version 1: its own SQLite file, or the test Postgres emptied first."""
    url = db.database_url(tmp_path)
    if url.startswith("sqlite"):
        url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    else:
        conn = db.connect(tmp_path)
        with conn:
            for table in db.TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        conn.close()
    db._ready.discard(url)  # this process checked it before; it must look again
    engine = create_engine(url)
    conn = db.Connection(engine.connect(), url)
    with conn:
        _version_1_database(conn)
    conn.close()
    engine.dispose()
    return url


def test_version_1_database_moves_to_icps(tmp_path: Path, old_url: str) -> None:
    conn = db.connect(tmp_path, url=old_url)
    try:
        assert db._read_schema_version(conn) == db.SCHEMA_VERSION == 3
        assert all(row["likely_chain"] == 0 for row in db.list_companies(conn))  # version 3
        rows = {row["domain"]: row["icp"] for row in db.list_companies(conn)}
        assert rows == {"firm1.com": "ai_accounting", "firm2.com": "ai_accounting",
                        "firm3.com": "old_thing"}  # fmt: skip
        assert db.list_batches(conn)[0]["icp"] == "ai_accounting"
        progress = db.get_progress(conn, "ai_accounting", "apollo")
        assert (progress["next_page"], progress["total_entries"]) == (2, 900)
        assert (
            db.usage_this_month.__name__
            and conn.execute("SELECT amount FROM usage WHERE provider = 'apollo'").fetchone()[
                "amount"
            ]
            == 1
        )
        # every company still points at a real ICP, the unknown one as an inactive placeholder
        placeholder = icps.get(conn, "old_thing")
        assert placeholder is not None and not placeholder.active
        assert icps.get(conn, "ai_accounting").sources["apollo"]["keywords"] == [
            "accounting",
            "bookkeeping",
        ]
        assert icps.get(conn, "dev_us_pain").active
    finally:
        conn.close()
    again = db.connect(tmp_path, url=old_url)  # a second start changes nothing
    try:
        assert db._read_schema_version(again) == 3
        assert len(db.list_companies(again)) == 3
    finally:
        again.close()


def test_schema_is_checked_once_per_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{(tmp_path / 'once.db').as_posix()}"
    db.connect(tmp_path, url=url).close()
    calls: list[object] = []
    monkeypatch.setattr(db, "init_schema", lambda conn: calls.append(conn))
    for _ in range(3):
        db.connect(tmp_path, url=url).close()
    assert calls == []
