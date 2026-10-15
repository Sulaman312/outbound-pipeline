"""SQLite connection, schema, and every SQL statement the pipeline uses.

Functions here never commit. Callers wrap one unit of work in `with conn:`,
which commits when the block succeeds and rolls back when it fails.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2

# Version 1: the tables every database starts with.
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

# Each later version, as the SQL that upgrades the one before it. Never edit a released entry:
# add a new one. Existing databases keep all their data.
MIGRATIONS: dict[int, str] = {
    2: """
    CREATE TABLE IF NOT EXISTS batches (
        id            INTEGER PRIMARY KEY,
        file          TEXT NOT NULL,                -- the CSV written for Clay
        rows          INTEGER NOT NULL,
        segment       TEXT,                         -- NULL when the batch mixes segments
        exported_at   TEXT NOT NULL,
        imported_at   TEXT,                         -- when Clay's results came back
        clay_account  TEXT,                         -- free text, e.g. which Clay login ran it
        clay_credits  REAL                          -- credits Clay used, typed in by hand
    );

    ALTER TABLE companies ADD COLUMN batch_id INTEGER REFERENCES batches(id);

    CREATE TABLE IF NOT EXISTS contacts (
        id            INTEGER PRIMARY KEY,
        company_id    INTEGER NOT NULL REFERENCES companies(id),
        batch_id      INTEGER REFERENCES batches(id),
        first_name    TEXT,
        last_name     TEXT,
        title         TEXT,
        email         TEXT UNIQUE,                  -- normalized; NULL when Clay found none
        linkedin_url  TEXT,
        clay_status   TEXT NOT NULL,                -- valid | invalid | catch_all | unknown | none
        decision      TEXT NOT NULL,                -- ready | maybe | hold | drop
        reason        TEXT NOT NULL,
        raw           TEXT,                         -- Clay's row as exported
        created_at    TEXT NOT NULL
    );
    """,
}

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
    """Create a new database, or upgrade an older one step by step. Refuse one from newer code."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema is version {version}, this code knows {SCHEMA_VERSION}. Update the code."
        )
    if version == 0:
        conn.executescript(SCHEMA)
        version = 1
    for target in range(version + 1, SCHEMA_VERSION + 1):
        conn.executescript(MIGRATIONS[target])
        conn.execute(f"PRAGMA user_version = {target}")
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


def raw_records(conn: sqlite3.Connection, segment: str | None = None) -> list[str]:
    """The provider's original JSON for each saved company."""
    sql = "SELECT raw FROM companies WHERE raw IS NOT NULL"
    params: tuple[str, ...] = ()
    if segment:
        sql += " AND segment = ?"
        params = (segment,)
    return [row["raw"] for row in conn.execute(sql + " ORDER BY id", params)]


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


def list_suppression(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The do-not-contact list, newest first."""
    return conn.execute(
        "SELECT value, kind, reason, added_at FROM suppression ORDER BY added_at DESC, value"
    ).fetchall()


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


# --- Clay batches -------------------------------------------------------------------------------


def _waiting_for_clay(segment: str | None) -> tuple[str, tuple[str, ...]]:
    """WHERE clause for new companies not yet sent to Clay, minus do-not-contact domains."""
    where = "status = 'new' AND domain NOT IN (SELECT value FROM suppression)"
    if segment:
        return where + " AND segment = ?", (segment,)
    return where, ()


def companies_for_clay(
    conn: sqlite3.Connection, segment: str | None, limit: int
) -> list[sqlite3.Row]:
    """Up to `limit` companies waiting for Clay, oldest first."""
    where, params = _waiting_for_clay(segment)
    return conn.execute(
        f"SELECT * FROM companies WHERE {where} ORDER BY id LIMIT ?", (*params, limit)
    ).fetchall()


def count_waiting_for_clay(conn: sqlite3.Connection, segment: str | None = None) -> int:
    where, params = _waiting_for_clay(segment)
    return conn.execute(f"SELECT COUNT(*) FROM companies WHERE {where}", params).fetchone()[0]


def create_batch(conn: sqlite3.Connection, file: str, rows: int, segment: str | None) -> int:
    cursor = conn.execute(
        "INSERT INTO batches (file, rows, segment, exported_at) VALUES (?, ?, ?, ?)",
        (file, rows, segment, now_utc()),
    )
    return int(cursor.lastrowid)


def mark_exported(conn: sqlite3.Connection, company_ids: list[int], batch_id: int) -> None:
    conn.executemany(
        "UPDATE companies SET status = 'exported', batch_id = ? WHERE id = ?",
        [(batch_id, company_id) for company_id in company_ids],
    )


def get_batch(conn: sqlite3.Connection, batch_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()


def finish_batch(
    conn: sqlite3.Connection, batch_id: int, account: str | None, credits: float | None
) -> None:
    """Record that Clay's results came back. Companies Clay returned nothing for become no_contact."""
    conn.execute(
        "UPDATE companies SET status = 'no_contact' WHERE batch_id = ? AND status = 'exported'",
        (batch_id,),
    )
    conn.execute(
        "UPDATE batches SET imported_at = ?, clay_account = COALESCE(?, clay_account), "
        "clay_credits = COALESCE(?, clay_credits) WHERE id = ?",
        (now_utc(), account, credits, batch_id),
    )


def list_batches(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every batch with what came back: people, emails, and each decision."""
    return conn.execute(
        """
        SELECT b.id, b.segment, b.rows, b.exported_at, b.imported_at, b.clay_account,
               b.clay_credits, b.file,
               COUNT(c.id) AS people,
               COUNT(c.email) AS emails,
               SUM(c.decision = 'ready') AS ready,
               SUM(c.decision = 'maybe') AS maybe,
               SUM(c.decision = 'hold') AS hold,
               SUM(c.decision = 'drop') AS dropped
        FROM batches b LEFT JOIN contacts c ON c.batch_id = b.id
        GROUP BY b.id ORDER BY b.id DESC
        """
    ).fetchall()


# --- contacts -----------------------------------------------------------------------------------


CONTACT_COLUMNS = (
    "company_id",
    "batch_id",
    "first_name",
    "last_name",
    "title",
    "email",
    "linkedin_url",
    "clay_status",
    "decision",
    "reason",
    "raw",
)


def get_company(conn: sqlite3.Connection, company_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()


def find_company_by_domain(conn: sqlite3.Connection, domain: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM companies WHERE domain = ?", (domain,)).fetchone()


def insert_contact(conn: sqlite3.Connection, contact: dict[str, Any]) -> bool:
    """Save a person. Returns False if we already have that email."""
    values = [contact.get(column) for column in CONTACT_COLUMNS] + [now_utc()]
    cursor = conn.execute(
        f"""
        INSERT INTO contacts ({", ".join(CONTACT_COLUMNS)}, created_at)
        VALUES ({", ".join("?" for _ in range(len(CONTACT_COLUMNS) + 1))})
        ON CONFLICT DO NOTHING
        """,
        values,
    )
    return cursor.rowcount == 1


def set_company_status(conn: sqlite3.Connection, company_id: int, status: str) -> None:
    """enriched always wins; no_contact never overwrites enriched."""
    if status == "enriched":
        conn.execute("UPDATE companies SET status = 'enriched' WHERE id = ?", (company_id,))
    else:
        conn.execute(
            "UPDATE companies SET status = ? WHERE id = ? AND status != 'enriched'",
            (status, company_id),
        )


def list_contacts(conn: sqlite3.Connection, decision: str | None = None) -> list[sqlite3.Row]:
    """People found by Clay, with their company, newest first."""
    sql = """
        SELECT c.email, c.first_name, c.last_name, c.title, co.domain AS company_domain,
               co.name AS company_name, co.segment, c.decision, c.reason, c.clay_status,
               c.linkedin_url, c.batch_id, c.created_at
        FROM contacts c JOIN companies co ON co.id = c.company_id
    """
    params: tuple[str, ...] = ()
    if decision:
        sql += " WHERE c.decision = ?"
        params = (decision,)
    return conn.execute(sql + " ORDER BY c.id DESC", params).fetchall()


def count_contacts(conn: sqlite3.Connection) -> dict[str, int]:
    """Number of contacts per decision."""
    rows = conn.execute("SELECT decision, COUNT(*) AS n FROM contacts GROUP BY decision").fetchall()
    return {row["decision"]: row["n"] for row in rows}
