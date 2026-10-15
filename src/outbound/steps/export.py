"""Write saved companies or contacts to a CSV file you can open in Excel or Google Sheets.

This only reads. It doesn't change any status, and it leaves out do-not-contact companies.
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
CONTACT_COLUMNS = (
    "email",
    "first_name",
    "last_name",
    "title",
    "company_domain",
    "company_name",
    "segment",
    "decision",
    "reason",
    "clay_status",
    "linkedin_url",
    "batch_id",
    "created_at",
)


def default_path(root: Path, kind: str = "companies") -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return root / "data" / "exports" / f"{kind}_{stamp}.csv"


def _plain(row: sqlite3.Row, columns: tuple[str, ...]) -> dict[str, object]:
    return {column: "" if row[column] is None else row[column] for column in columns}


def company_rows(conn: sqlite3.Connection, segment: str | None = None) -> list[dict[str, object]]:
    """Saved companies as plain rows with the export columns, for the CSV and the UI table."""
    return [_plain(row, COLUMNS) for row in db.list_companies(conn, segment)]


def contact_rows(conn: sqlite3.Connection, decision: str | None = None) -> list[dict[str, object]]:
    """Contacts as plain rows with the export columns, for the CSV and the UI table."""
    return [_plain(row, CONTACT_COLUMNS) for row in db.list_contacts(conn, decision)]


def csv_text(rows: list[dict[str, object]], columns: tuple[str, ...] = COLUMNS) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel on Windows shows accented names correctly
    path.write_text(text, encoding="utf-8-sig", newline="")


def export_companies(conn: sqlite3.Connection, path: Path, segment: str | None = None) -> int:
    """Write the companies CSV and return how many it holds."""
    rows = company_rows(conn, segment)
    _write(path, csv_text(rows))
    return len(rows)


def export_contacts(conn: sqlite3.Connection, path: Path, decision: str | None = None) -> int:
    """Write the contacts CSV and return how many it holds."""
    rows = contact_rows(conn, decision)
    _write(path, csv_text(rows, CONTACT_COLUMNS))
    return len(rows)
