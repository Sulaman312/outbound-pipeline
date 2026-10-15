"""Shared fixtures: a throwaway project folder, and no real API key in the environment."""

from __future__ import annotations

from pathlib import Path

import pytest

SETTINGS = """\
database: data/outbound.db
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


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts without a real key in the environment."""
    monkeypatch.delenv("APOLLO_API_KEY", raising=False)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A minimal valid project folder."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text(SETTINGS, encoding="utf-8")
    (tmp_path / "config" / "segments.yaml").write_text(SEGMENTS, encoding="utf-8")
    return tmp_path
