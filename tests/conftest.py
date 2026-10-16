"""Shared fixtures: a throwaway project folder, and no real secrets in the environment."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend import db

SETTINGS = """\
caps:
  apollo:
    credits: 10
  google_places:
    requests: 5
"""

_WIPE_ORDER = (
    "icp_sources",
    "icps",
    "leads",
    "batches",
    "companies",
    "suppression",
    "usage",
    "sourcing_progress",
    "query_progress",
    "places",
)


@pytest.fixture(autouse=True)
def no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts without a real key.

    Local runs always use SQLite. CI's Postgres job sets OUTBOUND_TEST_POSTGRES=1
    together with DATABASE_URL so tests hit the service container.
    """
    monkeypatch.delenv("APOLLO_API_KEY", raising=False)
    if os.environ.get("OUTBOUND_TEST_POSTGRES") != "1":
        monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture(autouse=True)
def wipe_shared_postgres() -> None:
    """When DATABASE_URL points at a shared Postgres, clear data between tests."""
    if os.environ.get("OUTBOUND_TEST_POSTGRES") != "1":
        yield
        return
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        yield
        return
    _wipe(url)
    yield
    _wipe(url)  # the URL captured above: a test may have unset DATABASE_URL by now


def _wipe(url: str) -> None:
    """Back to a freshly migrated database: empty tables, id counters at 1, starting ICPs."""
    conn = db.connect(Path.cwd(), url=url)
    try:
        with conn:
            conn.execute(f"TRUNCATE {', '.join(_WIPE_ORDER)} RESTART IDENTITY CASCADE")
            db.seed_starting_icps(conn)
    finally:
        conn.close()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A minimal valid project folder."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text(SETTINGS, encoding="utf-8")
    return tmp_path
