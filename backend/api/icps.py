"""ICPs (who we target) and the sources they can use. Create and edit; never delete."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import icps
from backend.api.deps import get_conn, sentence
from backend.db import Connection
from backend.sources import SOURCES

router = APIRouter(tags=["icps"])


class ActiveRequest(BaseModel):
    active: bool


@router.get("/sources")
def list_sources() -> list[dict[str, Any]]:
    return [asdict(source) for source in SOURCES]


@router.get("/icps")
def list_icps(conn: Annotated[Connection, Depends(get_conn)]) -> list[dict[str, Any]]:
    return icps.summaries(conn)


@router.get("/icps/{key}")
def get_icp(key: str, conn: Annotated[Connection, Depends(get_conn)]) -> dict[str, Any]:
    icp = icps.get(conn, key)
    if icp is None:
        raise HTTPException(404, f'No ICP called "{key}"')
    return asdict(icp)


def _saved(action: Callable[[], icps.Icp]) -> dict[str, Any]:
    """Run a save and turn its plain-words errors into 400 (bad input) or 404 (no such ICP)."""
    try:
        return asdict(action())
    except icps.IcpError as exc:
        raise HTTPException(400, sentence(str(exc))) from exc
    except LookupError as exc:
        raise HTTPException(404, sentence(str(exc))) from exc


@router.post("/icps")
def create_icp(
    body: dict[str, Any], conn: Annotated[Connection, Depends(get_conn)]
) -> dict[str, Any]:
    return _saved(lambda: icps.create(conn, body))


@router.put("/icps/{key}")
def update_icp(
    key: str, body: dict[str, Any], conn: Annotated[Connection, Depends(get_conn)]
) -> dict[str, Any]:
    return _saved(lambda: icps.update(conn, key, body))


@router.post("/icps/{key}/active")
def set_active(
    key: str, body: ActiveRequest, conn: Annotated[Connection, Depends(get_conn)]
) -> dict[str, Any]:
    return _saved(lambda: icps.set_active(conn, key, body.active))
