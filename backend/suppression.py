"""Add a domain or an email to the do-not-contact list. Entries are never removed."""

from __future__ import annotations

from backend import db
from backend.db import Connection
from backend.normalize import normalize_domain, normalize_email


def suppress(conn: Connection, value: str, reason: str) -> tuple[str, str, bool]:
    """Returns (normalized value, kind, newly added?). Raises ValueError for bad input."""
    if not reason.strip():
        raise ValueError('give a reason, like "existing client"')
    if "@" in value:
        kind, normalized = "email", normalize_email(value)
    else:
        kind, normalized = "domain", normalize_domain(value)
    if not normalized:
        raise ValueError(f"{value!r} isn't a valid domain or email")
    with conn:
        added = db.add_suppression(conn, normalized, kind, reason.strip())
    return normalized, kind, added
