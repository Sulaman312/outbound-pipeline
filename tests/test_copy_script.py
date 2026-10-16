"""scripts/copy_sqlite_to_db.py: copy an old schema-v2 SQLite file into the current database."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from backend import db

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "copy_sqlite_to_db.py"
_SPEC = importlib.util.spec_from_file_location("copy_sqlite_to_db", _SCRIPT)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
copy_sqlite = _MOD.copy_sqlite


def _build_old_sqlite(path: Path) -> None:
    """Minimal schema-v2 SQLite database like the pre-M0a layout."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE companies (
            id INTEGER PRIMARY KEY,
            domain TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            segment TEXT NOT NULL,
            city TEXT, state TEXT, country TEXT, employees INTEGER, industry TEXT,
            linkedin_url TEXT, raw TEXT,
            status TEXT NOT NULL DEFAULT 'new',
            batch_id INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE (source, source_id)
        );
        CREATE TABLE suppression (
            value TEXT PRIMARY KEY, kind TEXT NOT NULL, reason TEXT NOT NULL, added_at TEXT NOT NULL
        );
        CREATE TABLE usage (
            provider TEXT NOT NULL, unit TEXT NOT NULL, month TEXT NOT NULL,
            amount INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (provider, unit, month)
        );
        CREATE TABLE sourcing_progress (
            segment TEXT PRIMARY KEY, filters_hash TEXT NOT NULL, next_page INTEGER NOT NULL,
            total_entries INTEGER, exhausted INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
        );
        CREATE TABLE batches (
            id INTEGER PRIMARY KEY, file TEXT NOT NULL, rows INTEGER NOT NULL, segment TEXT,
            exported_at TEXT NOT NULL, imported_at TEXT, clay_account TEXT, clay_credits REAL
        );
        CREATE TABLE contacts (
            id INTEGER PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id),
            batch_id INTEGER REFERENCES batches(id),
            first_name TEXT, last_name TEXT, title TEXT,
            email TEXT UNIQUE, linkedin_url TEXT,
            clay_status TEXT NOT NULL,
            decision TEXT NOT NULL, reason TEXT NOT NULL,
            raw TEXT, created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO companies (id, domain, name, source, source_id, segment, status, created_at) "
        "VALUES (1, 'acme.com', 'Acme', 'apollo', 'org1', 'ai_accounting', 'enriched', "
        "'2026-10-15T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO batches (id, file, rows, segment, exported_at) "
        "VALUES (1, 'data/clay/batch.csv', 1, 'ai_accounting', '2026-10-15T01:00:00Z')"
    )
    conn.execute(
        "INSERT INTO contacts (id, company_id, batch_id, email, clay_status, decision, reason, "
        "created_at) VALUES (1, 1, 1, 'jane@acme.com', 'valid', 'ready', 'Clay says valid', "
        "'2026-10-15T02:00:00Z')"
    )
    conn.execute(
        "INSERT INTO contacts (id, company_id, batch_id, email, clay_status, decision, reason, "
        "created_at) VALUES (2, 1, 1, 'maybe@acme.com', 'catch_all', 'maybe', "
        "'Clay says catch-all', '2026-10-15T02:00:00Z')"
    )
    conn.execute(
        "INSERT INTO suppression (value, kind, reason, added_at) "
        "VALUES ('blocked.com', 'domain', 'client', '2026-10-15T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO usage (provider, unit, month, amount) VALUES ('apollo', 'credits', '2026-10', 3)"
    )
    conn.commit()
    conn.close()


@pytest.fixture
def old_db(tmp_path: Path) -> Path:
    path = tmp_path / "old" / "outbound.db"
    path.parent.mkdir(parents=True)
    _build_old_sqlite(path)
    return path


def test_copy_sqlite_maps_decisions_and_is_idempotent(tmp_path: Path, old_db: Path) -> None:
    dest_root = tmp_path / "dest"
    dest = db.connect(dest_root)
    try:
        first = copy_sqlite(old_db, dest)
        assert first["companies"] == 1
        assert first["leads"] == 2
        assert first["suppression"] == 1
        assert first["usage"] == 1
        assert first["batches"] == 1

        leads = {row["email"]: row for row in db.list_leads(dest)}
        assert leads["jane@acme.com"]["state"] == "verified"
        assert leads["maybe@acme.com"]["state"] == "needs_check"
        assert leads["jane@acme.com"]["state_reason"] == "Clay says valid"

        second = copy_sqlite(old_db, dest)
        assert second["companies"] == 0
        assert second["leads"] == 0
        assert second["suppression"] == 0
        assert len(db.list_leads(dest)) == 2
    finally:
        dest.close()
