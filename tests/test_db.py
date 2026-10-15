"""db.py: schema, uniqueness rules, usage and suppression."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from outbound import db


def company(domain: str, source_id: str, **fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "domain": domain,
        "name": domain,
        "source": "apollo",
        "source_id": source_id,
        "segment": "s",
    }
    base.update(fields)
    return base


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "nested" / "test.db")
    yield connection
    connection.close()


def test_connect_creates_file_and_tables(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "test.db"
    conn = db.connect(path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert path.is_file()
    assert {"companies", "suppression", "usage", "sourcing_progress"} <= tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    db.init_schema(conn)  # running it again is fine
    conn.close()


def test_newer_database_is_refused(conn: sqlite3.Connection) -> None:
    conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError, match="newer|Update the code"):
        db.init_schema(conn)


def test_duplicate_domain_or_provider_id_is_skipped(conn: sqlite3.Connection) -> None:
    with conn:
        assert db.insert_company(conn, company("a.com", "1")) is True
        assert db.insert_company(conn, company("a.com", "2")) is False  # same domain
        assert db.insert_company(conn, company("b.com", "1")) is False  # same Apollo id
    assert db.count_companies(conn) == {"s": 1}


def test_missing_required_field_still_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_company(conn, company("c.com", "3", name=None))


def test_usage_adds_up(conn: sqlite3.Connection) -> None:
    assert db.usage_this_month(conn, "apollo", "credits") == 0
    with conn:
        db.add_usage(conn, "apollo", "credits", 1)
        db.add_usage(conn, "apollo", "credits", 2)
    assert db.usage_this_month(conn, "apollo", "credits") == 3


def test_suppression_and_listing(conn: sqlite3.Connection) -> None:
    with conn:
        db.insert_company(conn, company("keep.com", "1"))
        db.insert_company(conn, company("blocked.com", "2"))
        assert db.add_suppression(conn, "blocked.com", "domain", "client") is True
        assert db.add_suppression(conn, "blocked.com", "domain", "again") is False
    assert db.is_suppressed(conn, "blocked.com")
    assert [row["domain"] for row in db.list_companies(conn)] == ["keep.com"]
    assert db.count_suppression(conn) == 1


def test_progress_round_trip(conn: sqlite3.Connection) -> None:
    assert db.get_progress(conn, "s") is None
    with conn:
        db.save_progress(conn, "s", "hash1", 2, 500, False)
        db.save_progress(conn, "s", "hash1", 3, 510, True)
    row = db.get_progress(conn, "s")
    assert (row["next_page"], row["total_entries"], row["exhausted"]) == (3, 510, 1)
