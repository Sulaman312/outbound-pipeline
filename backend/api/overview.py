"""GET /api/overview: the Pipeline board."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from backend import overview
from backend.api.deps import get_conn, get_settings
from backend.config import Settings
from backend.db import Connection

router = APIRouter(tags=["overview"])


@router.get("/overview")
def get_overview(
    conn: Annotated[Connection, Depends(get_conn)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    return overview.overview(conn, settings)
