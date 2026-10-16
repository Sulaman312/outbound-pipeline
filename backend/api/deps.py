"""What every route needs: the project folder, config, and one database connection per request.

The connection opens when a request starts and closes when it ends, so the shared Supabase
database never holds an idle transaction for us.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import HTTPException, Request

from backend import db, icps
from backend.config import Settings, load_settings
from backend.db import Connection
from backend.icps import Icp


def get_root(request: Request) -> Path:
    return request.app.state.root


def get_settings(request: Request) -> Settings:
    """Read config/settings.yaml on every request, so a changed cap applies without a restart."""
    return load_settings(get_root(request))


def get_conn(request: Request) -> Iterator[Connection]:
    conn = db.connect(get_root(request))
    try:
        yield conn
    finally:
        conn.close()


def icp_or_400(conn: Connection, key: str | None) -> Icp | None:
    """The ICP called `key`, None for "every ICP", or a 400 error."""
    if not key:
        return None
    icp = icps.get(conn, key)
    if icp is None:
        raise HTTPException(400, f'No ICP called "{key}". See the ICPs page.')
    return icp


def sentence(text: str) -> str:
    """A stage's error message ("pages must be ...") as a sentence for the screen."""
    return text[:1].upper() + text[1:]
