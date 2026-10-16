"""Saved companies or leads as CSV for the app's Download CSV buttons (opens in Excel or Sheets).

This only reads. It doesn't change any status, and it leaves out do-not-contact companies.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
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


def filename(kind: str) -> str:
    """The name a downloaded CSV gets, like companies_20261016-120000.csv."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{kind}_{stamp}.csv"


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
