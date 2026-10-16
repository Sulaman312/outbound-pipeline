"""People Clay found: list by state, and the same list as a CSV download."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response

from backend import db, exports
from backend.api.companies import SHOWN, csv_response
from backend.api.deps import get_conn
from backend.db import Connection
from backend.pipeline import LEAD_STATES

router = APIRouter(tags=["leads"])


def _check_state(state: str | None) -> None:
    if state and state not in LEAD_STATES:
        raise HTTPException(400, f"No lead state called {state!r}")


@router.get("/leads")
def list_leads(
    conn: Annotated[Connection, Depends(get_conn)], state: str | None = None
) -> dict[str, Any]:
    _check_state(state)
    rows = exports.lead_rows(conn, state)
    return {
        "total": len(rows),
        "shown": min(len(rows), SHOWN),
        "rows": rows[:SHOWN],
        "states": list(LEAD_STATES),
        "counts": db.count_leads(conn),
    }


@router.get("/leads.csv")
def download_leads(
    conn: Annotated[Connection, Depends(get_conn)], state: str | None = None
) -> Response:
    _check_state(state)
    text = exports.csv_text(exports.lead_rows(conn, state), exports.LEAD_COLUMNS)
    return csv_response(text, exports.filename("contacts"))
