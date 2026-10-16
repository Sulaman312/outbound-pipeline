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
"""

SEGMENTS = """\
segments:
  ai_accounting:
    offer: ai_automation
    description: US accounting firms, 1-20 staff
    employees: ["1,20"]
    locations: ["United States"]
    keywords: ["accounting", "bookkeeping"]
  frontend_agencies:
    offer: frontend
    description: US web agencies, 1-20 staff
    employees: ["1,10", "11,20"]
    locations: ["United States"]
    keywords: []
"""

_WIPE_ORDER = (
    "leads",
    "batches",
    "companies",
    "suppression",
    "usage",
    "sourcing_progress",
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
    root = Path.cwd()
    conn = db.connect(root)
    try:
        with conn:
            for table in _WIPE_ORDER:
                if db._table_exists(conn, table):
                    conn.execute(f"DELETE FROM {table}")
    finally:
        conn.close()
    yield
    conn = db.connect(root)
    try:
        with conn:
            for table in _WIPE_ORDER:
                if db._table_exists(conn, table):
                    conn.execute(f"DELETE FROM {table}")
    finally:
        conn.close()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A minimal valid project folder."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text(SETTINGS, encoding="utf-8")
    (tmp_path / "config" / "segments.yaml").write_text(SEGMENTS, encoding="utf-8")
    return tmp_path
