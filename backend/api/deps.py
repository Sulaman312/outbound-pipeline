"""What every route needs: the project folder, config, and one database connection per request.

The connection opens when a request starts and closes when it ends, so the shared Supabase
database never holds an idle transaction for us.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import HTTPException, Request

from backend import db
from backend.config import Segment, Settings, load_segments, load_settings
from backend.db import Connection


def get_root(request: Request) -> Path:
    return request.app.state.root


def get_settings(request: Request) -> Settings:
    """Read config/settings.yaml on every request, so a changed cap applies without a restart."""
    return load_settings(get_root(request))


def get_segments(request: Request) -> dict[str, Segment]:
    return load_segments(get_root(request))


def get_conn(request: Request) -> Iterator[Connection]:
    conn = db.connect(get_root(request))
    try:
        yield conn
    finally:
        conn.close()


def segment_or_400(segments: dict[str, Segment], key: str | None) -> Segment | None:
    """The segment called `key`, None for "all segments", or a 400 error naming the choices."""
    if not key:
        return None
    if key not in segments:
        raise HTTPException(
            400, f"No segment called {key!r}. Choose one of: {', '.join(sorted(segments))}"
        )
    return segments[key]


def sentence(text: str) -> str:
    """A stage's error message ("pages must be ...") as a sentence for the screen."""
    return text[:1].upper() + text[1:]
