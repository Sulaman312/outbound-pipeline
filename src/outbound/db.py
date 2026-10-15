"""SQLite connection, schema, and every SQL statement the pipeline uses.

Functions here never commit. Callers wrap one unit of work in `with conn:`,
which commits when the block succeeds and rolls back when it fails.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id            INTEGER PRIMARY KEY,
    domain        TEXT NOT NULL UNIQUE,         -- normalized: lowercase, no scheme, no www, no path
    name          TEXT NOT NULL,
    source        TEXT NOT NULL,                -- 'apollo'
    source_id     TEXT NOT NULL,                -- the provider's own id for this company
    segment       TEXT NOT NULL,                -- key from config/segments.yaml
    city          TEXT,
    state         TEXT,
    country       TEXT,
    employees     INTEGER,                      -- as reported by the source; NULL if unknown
    industry      TEXT,
    linkedin_url  TEXT,
    raw           TEXT,                         -- the provider's JSON for this record
    status        TEXT NOT NULL DEFAULT 'new',  -- new | exported | enriched | no_contact
    created_at    TEXT NOT NULL,                -- UTC, like 2026-10-15T09:30:00Z
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS suppression (
    value     TEXT PRIMARY KEY,                 -- lowercase email, domain, or sha256 hex of an email
    kind      TEXT NOT NULL,                    -- email | domain | email_hash
    reason    TEXT NOT NULL,
    added_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage (
    provider  TEXT NOT NULL,                    -- apollo
    unit      TEXT NOT NULL,                    -- credits
    month     TEXT NOT NULL,                    -- YYYY-MM, UTC
    amount    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (provider, unit, month)
);

CREATE TABLE IF NOT EXISTS sourcing_progress (
    segment        TEXT PRIMARY KEY,
    filters_hash   TEXT NOT NULL,               -- changes when the segment's filters change
    next_page      INTEGER NOT NULL,            -- the first page the next run fetches
    total_entries  INTEGER,                     -- how many matches the provider reported last time
    exhausted      INTEGER NOT NULL DEFAULT 0,  -- 1 when there are no more pages
    updated_at     TEXT NOT NULL
);
"""

COMPANY_COLUMNS = (
    "domain",
    "name",
    "source",
    "source_id",
    "segment",
    "city",
    "state",
    "country",
    "employees",
    "industry",
    "linkedin_url",
    "raw",
)


def connect(path: Path) -> sqlite3.Connection:
    """Open the database (creating the file and folder if needed) and make sure tables exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create missing tables. Refuse a database made by newer code."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema is version {version}, this code knows {SCHEMA_VERSION}. Update the code."
        )
    conn.executescript(SCHEMA)
    if version == 0:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def now_utc() -> str:
    """Current UTC time, like 2026-10-15T09:30:00Z."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_month() -> str:
    """Current UTC month, like 2026-10."""
    return datetime.now(UTC).strftime("%Y-%m")


# --- usage --------------------------------------------------------------------------------------


def usage_this_month(conn: sqlite3.Connection, provider: str, unit: str) -> int:
    row = conn.execute(
        "SELECT amount FROM usage WHERE provider = ? AND unit = ? AND month = ?",
        (provider, unit, current_month()),
    ).fetchone()
    return row["amount"] if row else 0


def add_usage(conn: sqlite3.Connection, provider: str, unit: str, amount: int) -> None:
    conn.execute(
        """
        INSERT INTO usage (provider, unit, month, amount) VALUES (?, ?, ?, ?)
        ON CONFLICT (provider, unit, month) DO UPDATE SET amount = amount + excluded.amount
        """,
        (provider, unit, current_month(), amount),
    )


# --- companies ----------------------------------------------------------------------------------


def insert_company(conn: sqlite3.Connection, company: dict[str, Any]) -> bool:
    """Save a company. Returns False if we already have its domain or provider id."""
    values = [company.get(column) for column in COMPANY_COLUMNS] + [now_utc()]
    cursor = conn.execute(
        f"""
        INSERT INTO companies ({", ".join(COMPANY_COLUMNS)}, created_at)
        VALUES ({", ".join("?" for _ in range(len(COMPANY_COLUMNS) + 1))})
        ON CONFLICT DO NOTHING
        """,
        values,
    )
    return cursor.rowcount == 1


def list_companies(conn: sqlite3.Connection, segment: str | None = None) -> list[sqlite3.Row]:
    """Saved companies, oldest first, leaving out any domain on the do-not-contact list."""
    sql = "SELECT * FROM companies WHERE domain NOT IN (SELECT value FROM suppression)"
    params: tuple[str, ...] = ()
    if segment:
        sql += " AND segment = ?"
        params = (segment,)
    return conn.execute(sql + " ORDER BY id", params).fetchall()


def count_companies(conn: sqlite3.Connection) -> dict[str, int]:
    """Number of saved companies per segment."""
    rows = conn.execute("SELECT segment, COUNT(*) AS n FROM companies GROUP BY segment").fetchall()
    return {row["segment"]: row["n"] for row in rows}


# --- suppression --------------------------------------------------------------------------------


def is_suppressed(conn: sqlite3.Connection, value: str) -> bool:
    row = conn.execute("SELECT 1 FROM suppression WHERE value = ?", (value,)).fetchone()
    return row is not None


def add_suppression(conn: sqlite3.Connection, value: str, kind: str, reason: str) -> bool:
    """Add an entry. Returns False if it was already there. Entries are never removed."""
    cursor = conn.execute(
        "INSERT INTO suppression (value, kind, reason, added_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (value) DO NOTHING",
        (value, kind, reason, now_utc()),
    )
    return cursor.rowcount == 1


def count_suppression(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM suppression").fetchone()[0]


# --- sourcing progress --------------------------------------------------------------------------


def get_progress(conn: sqlite3.Connection, segment: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sourcing_progress WHERE segment = ?", (segment,)).fetchone()


def save_progress(
    conn: sqlite3.Connection,
    segment: str,
    filters_hash: str,
    next_page: int,
    total_entries: int | None,
    exhausted: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO sourcing_progress
            (segment, filters_hash, next_page, total_entries, exhausted, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (segment) DO UPDATE SET
            filters_hash = excluded.filters_hash,
            next_page = excluded.next_page,
            total_entries = excluded.total_entries,
            exhausted = excluded.exhausted,
            updated_at = excluded.updated_at
        """,
        (segment, filters_hash, next_page, total_entries, int(exhausted), now_utc()),
    )
