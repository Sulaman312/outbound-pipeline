"""Write saved companies to a CSV file you can open in Excel or Google Sheets.

This only reads. It doesn't change any company's status, and it leaves out do-not-contact domains.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from outbound import db

# Headcount, location and industry columns come back once the email step fills them.
COLUMNS = ("domain", "name", "segment", "linkedin_url", "status", "source", "created_at")


def default_path(root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return root / "data" / "exports" / f"companies_{stamp}.csv"


def company_rows(conn: sqlite3.Connection, segment: str | None = None) -> list[dict[str, object]]:
    """Saved companies as plain rows with the export columns, for the CSV and the UI table."""
    return [
        {column: "" if row[column] is None else row[column] for column in COLUMNS}
        for row in db.list_companies(conn, segment)
    ]


def csv_text(rows: list[dict[str, object]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def export_companies(conn: sqlite3.Connection, path: Path, segment: str | None = None) -> int:
    """Write the CSV and return how many companies it holds."""
    rows = company_rows(conn, segment)
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel on Windows shows accented names correctly
    path.write_text(csv_text(rows), encoding="utf-8-sig", newline="")
    return len(rows)
