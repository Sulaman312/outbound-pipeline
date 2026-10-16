"""The do-not-contact list: see it and add to it. There is no route to remove an entry."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import db, suppression
from backend.api.deps import get_conn
from backend.db import Connection

router = APIRouter(tags=["do-not-contact"])


class SuppressRequest(BaseModel):
    value: str
    reason: str


@router.get("/suppression")
def list_suppression(conn: Annotated[Connection, Depends(get_conn)]) -> list[dict[str, Any]]:
    return [dict(row) for row in db.list_suppression(conn)]


@router.post("/suppression")
def add(body: SuppressRequest, conn: Annotated[Connection, Depends(get_conn)]) -> dict[str, Any]:
    try:
        value, kind, added = suppression.suppress(conn, body.value, body.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"value": value, "kind": kind, "added": added}
