"""Write saved companies to a CSV file you can open in Excel or Google Sheets.

This only reads. It doesn't change any company's status, and it leaves out do-not-contact domains.
"""

from __future__ import annotations

import csv
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from outbound import db

COLUMNS = (
    "domain",
    "name",
    "segment",
    "city",
    "state",
    "country",
    "employees",
    "industry",
    "linkedin_url",
    "status",
    "source",
    "created_at",
)


def default_path(root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return root / "data" / "exports" / f"companies_{stamp}.csv"


def export_companies(conn: sqlite3.Connection, path: Path, segment: str | None = None) -> int:
    """Write the CSV and return how many companies it holds."""
    rows = db.list_companies(conn, segment)
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel on Windows shows accented names correctly
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow(["" if row[column] is None else row[column] for column in COLUMNS])
    return len(rows)
