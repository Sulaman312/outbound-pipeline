"""Write saved companies or leads to a CSV file you can open in Excel or Google Sheets.

This only reads. It doesn't change any status, and it leaves out do-not-contact companies.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend import db
from backend.db import Connection

# Headcount, location and industry columns come back once the email step fills them.
COLUMNS = (
    "domain",
    "name",
    "icp",
    "source",
    "city",
    "state",
    "linkedin_url",
    "status",
    "likely_chain",
    "created_at",
)
LEAD_COLUMNS = (
    "email",
    "first_name",
    "last_name",
    "title",
    "company_domain",
    "company_name",
    "icp",
    "state",
    "state_reason",
    "clay_status",
    "linkedin_url",
    "batch_id",
    "created_at",
)


def default_path(root: Path, kind: str = "companies") -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return root / "data" / "exports" / f"{kind}_{stamp}.csv"


def _plain(row: Any, columns: tuple[str, ...]) -> dict[str, object]:
    return {column: "" if row[column] is None else row[column] for column in columns}


def company_rows(
    conn: Connection, icp: str | None = None, search: str | None = None, source: str | None = None
) -> list[dict[str, object]]:
    """Saved companies as plain rows with the export columns."""
    return [_plain(row, COLUMNS) for row in db.list_companies(conn, icp, search, source)]


def lead_rows(conn: Connection, state: str | None = None) -> list[dict[str, object]]:
    """Leads as plain rows with the export columns."""
    return [_plain(row, LEAD_COLUMNS) for row in db.list_leads(conn, state)]


def csv_text(rows: list[dict[str, object]], columns: tuple[str, ...] = COLUMNS) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def excel_bytes(text: str) -> bytes:
    """CSV text as bytes Excel on Windows opens with accented names intact (UTF-8 with BOM)."""
    return text.encode("utf-8-sig")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel on Windows shows accented names correctly
    path.write_text(text, encoding="utf-8-sig", newline="")


def export_companies(conn: Connection, path: Path, icp: str | None = None) -> int:
    """Write the companies CSV and return how many it holds."""
    rows = company_rows(conn, icp)
    _write(path, csv_text(rows))
    return len(rows)


def export_leads(conn: Connection, path: Path, state: str | None = None) -> int:
    """Write the leads CSV and return how many it holds."""
    rows = lead_rows(conn, state)
    _write(path, csv_text(rows, LEAD_COLUMNS))
    return len(rows)
