"""Saved companies: list with search, and the same list as a CSV download."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response

from backend import exports
from backend.api.deps import get_conn, get_segments, segment_or_400
from backend.config import Segment
from backend.db import Connection

router = APIRouter(tags=["companies"])

SHOWN = 500  # rows the table shows; the CSV has all of them


@router.get("/companies")
def list_companies(
    conn: Annotated[Connection, Depends(get_conn)],
    segments: Annotated[dict[str, Segment], Depends(get_segments)],
    segment: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    segment_or_400(segments, segment)
    rows = exports.company_rows(conn, segment, search)
    return {"total": len(rows), "shown": min(len(rows), SHOWN), "rows": rows[:SHOWN]}


@router.get("/companies.csv")
def download_companies(
    conn: Annotated[Connection, Depends(get_conn)],
    segments: Annotated[dict[str, Segment], Depends(get_segments)],
    segment: str | None = None,
    search: str | None = None,
) -> Response:
    segment_or_400(segments, segment)
    text = exports.csv_text(exports.company_rows(conn, segment, search))
    return csv_response(text, exports.default_path(Path("."), "companies").name)


def csv_response(text: str, filename: str) -> Response:
    """A CSV file download that Excel opens with accented names intact."""
    return Response(
        exports.excel_bytes(text),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
