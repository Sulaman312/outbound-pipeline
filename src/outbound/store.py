"""SQLite store: the single source of truth for leads between stages.

Why SQLite: one file, no server, survives between runs, and lets every stage
pick up exactly the leads at its input stage. Leads are stored as JSON (the
pydantic model) plus a few indexed columns used for lookups, so adding a field
to `Lead` never needs a migration.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from outbound.models import Lead, SourcedRecord, Stage, utcnow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    icp        TEXT NOT NULL,
    key        TEXT NOT NULL,
    country    TEXT NOT NULL,
    stage      TEXT NOT NULL,
    domain     TEXT,
    email      TEXT,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (icp, key)
);
CREATE INDEX IF NOT EXISTS leads_stage ON leads (icp, country, stage);
CREATE INDEX IF NOT EXISTS leads_domain ON leads (domain);

-- Every raw provider hit, kept for audit and so a re-mapping never needs a re-fetch.
CREATE TABLE IF NOT EXISTS raw_records (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL,
    source     TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    payload    TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stage       TEXT NOT NULL,
    params      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    stats       TEXT
);

-- Paid/limited API calls per provider per calendar month (budget guard).
CREATE TABLE IF NOT EXISTS usage (
    provider TEXT NOT NULL,
    month    TEXT NOT NULL,
    units    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (provider, month)
);

-- Never email these again. kind = 'email' or 'domain'. Nothing is ever deleted.
CREATE TABLE IF NOT EXISTS suppression (
    kind     TEXT NOT NULL,
    value    TEXT NOT NULL,
    reason   TEXT,
    added_at TEXT NOT NULL,
    PRIMARY KEY (kind, value)
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._db:
            yield

    # ---- leads -----------------------------------------------------------

    def get_lead(self, icp: str, key: str) -> Lead | None:
        row = self._db.execute(
            "SELECT id, data FROM leads WHERE icp = ? AND key = ?", (icp, key)
        ).fetchone()
        return self._to_lead(row) if row else None

    def find_by_domain(self, icp: str, domain: str) -> Lead | None:
        row = self._db.execute(
            "SELECT id, data FROM leads WHERE icp = ? AND domain = ?", (icp, domain)
        ).fetchone()
        return self._to_lead(row) if row else None

    def save_lead(self, lead: Lead) -> Lead:
        """Insert or update. Returns the lead with its id set."""
        lead.updated_at = utcnow()
        data = lead.model_dump_json(exclude={"id"})
        params = (
            lead.icp,
            lead.key,
            lead.country,
            lead.stage.value,
            lead.company.domain,
            lead.email,
            data,
            lead.updated_at.isoformat(),
        )
        if lead.id is None:
            cur = self._db.execute(
                "INSERT INTO leads (icp, key, country, stage, domain, email, data, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                params,
            )
            lead.id = cur.lastrowid
        else:
            self._db.execute(
                "UPDATE leads SET icp=?, key=?, country=?, stage=?, domain=?, email=?, data=?,"
                " updated_at=? WHERE id=?",
                (*params, lead.id),
            )
        return lead

    def leads(
        self, icp: str | None = None, country: str | None = None, stage: Stage | None = None
    ) -> Iterator[Lead]:
        sql, args = "SELECT id, data FROM leads WHERE 1=1", []
        for col, val in (
            ("icp", icp),
            ("country", country),
            ("stage", stage.value if stage else None),
        ):
            if val is not None:
                sql += f" AND {col} = ?"
                args.append(val)
        for row in self._db.execute(sql + " ORDER BY id", args):
            yield self._to_lead(row)

    @staticmethod
    def _to_lead(row: sqlite3.Row) -> Lead:
        lead = Lead.model_validate_json(row["data"])
        lead.id = row["id"]
        return lead

    # ---- raw records and runs -------------------------------------------

    def save_raw(self, run_id: int, record: SourcedRecord) -> None:
        self._db.execute(
            "INSERT INTO raw_records (run_id, source, source_id, payload, fetched_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (run_id, record.source, record.source_id, json.dumps(record.raw), utcnow().isoformat()),
        )

    def start_run(self, stage: str, params: dict) -> int:
        with self._db:
            cur = self._db.execute(
                "INSERT INTO runs (stage, params, started_at) VALUES (?, ?, ?)",
                (stage, json.dumps(params), utcnow().isoformat()),
            )
        return cur.lastrowid

    def finish_run(self, run_id: int, stats: dict) -> None:
        with self._db:
            self._db.execute(
                "UPDATE runs SET finished_at = ?, stats = ? WHERE id = ?",
                (utcnow().isoformat(), json.dumps(stats), run_id),
            )

    # ---- usage (budget guard) ---------------------------------------------

    def usage(self, provider: str, month: str) -> int:
        row = self._db.execute(
            "SELECT units FROM usage WHERE provider = ? AND month = ?", (provider, month)
        ).fetchone()
        return row["units"] if row else 0

    def add_usage(self, provider: str, month: str, units: int = 1) -> None:
        # Committed immediately: a crash later in the run must not forget spend.
        with self._db:
            self._db.execute(
                "INSERT INTO usage (provider, month, units) VALUES (?, ?, ?)"
                " ON CONFLICT (provider, month) DO UPDATE SET units = units + excluded.units",
                (provider, month, units),
            )

    # ---- suppression ------------------------------------------------------

    def suppress(self, kind: str, value: str, reason: str | None = None) -> None:
        if kind not in ("email", "domain"):
            raise ValueError("kind must be 'email' or 'domain'")
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO suppression (kind, value, reason, added_at)"
                " VALUES (?, ?, ?, ?)",
                (kind, value.lower(), reason, utcnow().isoformat()),
            )

    def is_suppressed(self, email: str | None = None, domain: str | None = None) -> bool:
        checks = []
        if email:
            checks.append(("email", email.lower()))
            checks.append(("domain", email.rsplit("@", 1)[-1].lower()))
        if domain:
            checks.append(("domain", domain.lower()))
        for kind, value in checks:
            if self._db.execute(
                "SELECT 1 FROM suppression WHERE kind = ? AND value = ?", (kind, value)
            ).fetchone():
                return True
        return False
