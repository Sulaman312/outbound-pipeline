"""db.py: schema, uniqueness rules, usage, suppression, credit reserve, Clay claim."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from backend import db


def company(domain: str, source_id: str, **fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "domain": domain,
        "name": domain,
        "source": "apollo",
        "source_id": source_id,
        "icp": "s",
    }
    base.update(fields)
    return base


@pytest.fixture
def conn(tmp_path: Path) -> db.Connection:
    connection = db.connect(tmp_path / "nested")
    yield connection
    connection.close()


def test_connect_creates_file_and_tables(tmp_path: Path) -> None:
    root = tmp_path / "a" / "b"
    conn = db.connect(root)
    assert db._table_exists(conn, "companies")
    assert db._table_exists(conn, "leads")
    assert db._table_exists(conn, "schema_version")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    assert row is not None and row["version"] == db.SCHEMA_VERSION
    with conn:
        db.init_schema(conn)  # running it again is fine
    if conn.url.startswith("sqlite:///"):
        assert (root / "data" / "outbound.db").is_file()
    conn.close()


def test_failed_block_rolls_back(conn: db.Connection) -> None:
    with pytest.raises(RuntimeError), conn:
        db.add_suppression(conn, "acme.com", "domain", "test")
        raise RuntimeError("boom")
    assert not db.is_suppressed(conn, "acme.com")


def test_inner_block_waits_for_the_outer_one(conn: db.Connection) -> None:
    with pytest.raises(RuntimeError), conn:
        with conn:
            db.add_suppression(conn, "acme.com", "domain", "test")
        raise RuntimeError("the outer block fails after the inner one finished")
    assert not db.is_suppressed(conn, "acme.com")


def test_read_before_block_does_not_break_it(conn: db.Connection) -> None:
    db.is_suppressed(conn, "acme.com")  # a read outside any block, like source.start_point
    with conn:
        db.add_suppression(conn, "acme.com", "domain", "test")
    assert db.is_suppressed(conn, "acme.com")


def test_newer_database_is_refused(tmp_path: Path) -> None:
    # Its own SQLite file, so a shared Postgres test database is never left at a future version.
    conn = db.connect(tmp_path, url=f"sqlite:///{(tmp_path / 'newer.db').as_posix()}")
    with conn:
        conn.execute("DELETE FROM schema_version")
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (:v)",
            {"v": db.SCHEMA_VERSION + 1},
        )
    with pytest.raises(RuntimeError, match="newer|Update the code"):
        with conn:
            db.init_schema(conn)
    conn.close()


def test_duplicate_domain_or_provider_id_is_skipped(conn: db.Connection) -> None:
    with conn:
        assert db.insert_company(conn, company("a.com", "1")) is True
        assert db.insert_company(conn, company("a.com", "2")) is False  # same domain
        assert db.insert_company(conn, company("b.com", "1")) is False  # same Apollo id
    assert db.count_companies(conn) == {"s": 1}


def test_missing_required_field_still_raises(conn: db.Connection) -> None:
    with pytest.raises(IntegrityError):
        with conn:
            db.insert_company(conn, company("c.com", "3", name=None))


def test_usage_adds_up(conn: db.Connection) -> None:
    assert db.usage_this_month(conn, "apollo", "credits") == 0
    with conn:
        db.add_usage(conn, "apollo", "credits", 1)
        db.add_usage(conn, "apollo", "credits", 2)
    assert db.usage_this_month(conn, "apollo", "credits") == 3


def test_reserve_usage_stops_at_cap(conn: db.Connection) -> None:
    with conn:
        assert db.reserve_usage(conn, "apollo", "credits", 1, cap=2) is True
        assert db.reserve_usage(conn, "apollo", "credits", 1, cap=2) is True
        assert db.reserve_usage(conn, "apollo", "credits", 1, cap=2) is False
    assert db.usage_this_month(conn, "apollo", "credits") == 2


def test_reserve_usage_keeps_reservation_on_failure_path(conn: db.Connection) -> None:
    """A failed call keeps its reservation so the cap is never exceeded by retries."""
    with conn:
        assert db.reserve_usage(conn, "apollo", "credits", 1, cap=1) is True
    # Simulate failed API: do nothing with the reservation.
    assert db.usage_this_month(conn, "apollo", "credits") == 1
    with conn:
        assert db.reserve_usage(conn, "apollo", "credits", 1, cap=1) is False


def test_suppression_and_listing(conn: db.Connection) -> None:
    with conn:
        db.insert_company(conn, company("keep.com", "1"))
        db.insert_company(conn, company("blocked.com", "2"))
        assert db.add_suppression(conn, "blocked.com", "domain", "client") is True
        assert db.add_suppression(conn, "blocked.com", "domain", "again") is False
    assert db.is_suppressed(conn, "blocked.com")
    assert [row["domain"] for row in db.list_companies(conn)] == ["keep.com"]
    assert db.count_suppression(conn) == 1


def test_progress_round_trip(conn: db.Connection) -> None:
    assert db.get_progress(conn, "s", "apollo") is None
    with conn:
        db.save_progress(conn, "s", "apollo", "hash1", 2, 500, False)
        db.save_progress(conn, "s", "apollo", "hash1", 3, 510, True)
    row = db.get_progress(conn, "s", "apollo")
    assert db.get_progress(conn, "s", "google_maps") is None  # kept per source
    assert row is not None
    assert (row["next_page"], row["total_entries"], row["exhausted"]) == (3, 510, 1)


def test_claim_companies_for_clay_never_overlaps(conn: db.Connection) -> None:
    with conn:
        for i in range(1, 6):
            db.insert_company(conn, company(f"firm{i}.com", f"org{i}"))
        db.add_suppression(conn, "firm2.com", "domain", "client")
        batch_a = db.create_batch(conn, "a.csv", 0, None)
        first = db.claim_companies_for_clay(conn, None, 2, batch_a)
        db.update_batch(conn, batch_a, file="a.csv", rows=len(first))
        batch_b = db.create_batch(conn, "b.csv", 0, None)
        second = db.claim_companies_for_clay(conn, None, 2, batch_b)
        db.update_batch(conn, batch_b, file="b.csv", rows=len(second))
        batch_c = db.create_batch(conn, "c.csv", 0, None)
        third = db.claim_companies_for_clay(conn, None, 2, batch_c)
    assert [row["domain"] for row in first] == ["firm1.com", "firm3.com"]
    assert [row["domain"] for row in second] == ["firm4.com", "firm5.com"]
    assert third == []
    assert {row["status"] for row in db.list_companies(conn)} == {"exported"}


def test_describe_database_never_includes_password() -> None:
    text = db.describe_database("postgresql+psycopg://user:s3cret@db.example.com:5432/outbound")
    assert text == "postgres at db.example.com"
    assert "s3cret" not in text


def test_a_closed_pooled_connection_is_replaced(project: Path) -> None:
    """Supabase may end an idle connection while `outbound serve` runs; the next request works."""
    first = db.connect(project)
    if first.dialect != "postgresql":
        first.close()
        pytest.skip("only a Postgres server ends idle connections")
    helper = db.connect(project)
    pid = first.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
    first.close()  # back to the pool, idle
    with helper:
        helper.execute("SELECT pg_terminate_backend(:pid)", {"pid": pid})
    helper.close()
    for _ in range(2):  # whichever pooled connection comes out first
        conn = db.connect(project)
        assert db.count_suppression(conn) == 0
        conn.close()
