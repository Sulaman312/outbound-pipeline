"""Saved companies: list with search, and the same list as a CSV download."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response

from backend import exports
from backend.api.deps import get_conn, icp_or_400
from backend.db import Connection

router = APIRouter(tags=["companies"])

SHOWN = 500  # rows the table shows; the CSV has all of them


@router.get("/companies")
def list_companies(
    conn: Annotated[Connection, Depends(get_conn)],
    icp: str | None = None,
    search: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    icp_or_400(conn, icp)
    rows = exports.company_rows(conn, icp, search, source)
    return {"total": len(rows), "shown": min(len(rows), SHOWN), "rows": rows[:SHOWN]}


@router.get("/companies.csv")
def download_companies(
    conn: Annotated[Connection, Depends(get_conn)],
    icp: str | None = None,
    search: str | None = None,
    source: str | None = None,
) -> Response:
    icp_or_400(conn, icp)
    text = exports.csv_text(exports.company_rows(conn, icp, search, source))
    return csv_response(text, exports.default_path(Path("."), "companies").name)


def csv_response(text: str, filename: str) -> Response:
    """A CSV file download that Excel opens with accented names intact."""
    return Response(
        exports.excel_bytes(text),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
