"""steps/source.py: dry run, filtering, saving, caps, and picking up where the last run stopped."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fakes import FakeApollo, org, page

from outbound import db
from outbound.config import Segment, load_segments
from outbound.steps import source


@pytest.fixture
def conn(project: Path) -> sqlite3.Connection:
    connection = db.connect(project / "data" / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def segment(project: Path) -> Segment:
    return load_segments(project)["ai_accounting"]


def run(
    conn: sqlite3.Connection, segment: Segment, fake: FakeApollo, *, pages: int = 1, cap: int = 10
) -> source.SourceResult:
    return source.run_live(conn, segment, client=fake.client(), api_key="key", cap=cap, pages=pages)


def test_dry_run_describes_without_network(conn: sqlite3.Connection, segment: Segment) -> None:
    text = source.describe(conn, segment, pages=2, cap=10)
    assert "request:  POST https://api.apollo.io/api/v1/mixed_companies/search" in text
    assert "q_organization_keyword_tags[] = accounting" in text
    assert "pages:    1 to 2" in text
    assert "up to 2 Apollo credit(s)" in text
    assert "0 of 10 credits used" in text


def test_dry_run_warns_when_cap_is_too_small(conn: sqlite3.Connection, segment: Segment) -> None:
    assert "room for only 1 page" in source.describe(conn, segment, pages=3, cap=1)


def test_live_run_filters_and_saves(conn: sqlite3.Connection, segment: Segment) -> None:
    with conn:
        db.add_suppression(conn, "blocked.com", "domain", "existing client")
    records = [
        org(1, "https://www.Good-One.com/"),
        org(2, "", website_url=None),  # no website at all
        org(3, "blocked.com"),
        org(4, "good-one.com"),  # same company again under another id
        org(5),
    ]
    fake = FakeApollo((200, page(records)))
    result = run(conn, segment, fake)

    assert (result.saved, result.duplicate, result.no_domain, result.suppressed) == (2, 1, 1, 1)
    assert result.seen == 5 and result.pages == 1 and result.credits == 1
    assert db.usage_this_month(conn, "apollo", "credits") == 1

    rows = {row["domain"]: row for row in db.list_companies(conn)}
    assert sorted(rows) == ["company5.com", "good-one.com"]
    saved = rows["good-one.com"]
    assert (saved["segment"], saved["source"], saved["source_id"]) == (
        "ai_accounting",
        "apollo",
        "org1",
    )
    assert saved["linkedin_url"] == "http://www.linkedin.com/company/company1"
    assert json.loads(saved["raw"])["id"] == "org1"


def test_record_without_primary_domain_uses_website(
    conn: sqlite3.Connection, segment: Segment
) -> None:
    fake = FakeApollo(
        (200, page([org(1, primary_domain=None, website_url="http://www.fallback.io")]))
    )
    run(conn, segment, fake)
    assert [row["domain"] for row in db.list_companies(conn)] == ["fallback.io"]


def test_next_run_continues_at_next_page(conn: sqlite3.Connection, segment: Segment) -> None:
    run(conn, segment, FakeApollo((200, page([org(1)], number=1))))
    fake = FakeApollo((200, page([org(2)], number=2)))
    result = run(conn, segment, fake)
    assert fake.pages_requested() == [2]
    assert result.next_page == 3


def test_changed_filters_start_again_at_page_one(
    conn: sqlite3.Connection, segment: Segment
) -> None:
    run(conn, segment, FakeApollo((200, page([org(1)]))))
    changed = Segment(**{**segment.__dict__, "keywords": ("tax",)})
    fake = FakeApollo((200, page([org(2)])))
    run(conn, changed, fake)
    assert fake.pages_requested() == [1]


def test_cap_stops_before_spending(conn: sqlite3.Connection, segment: Segment) -> None:
    fake = FakeApollo((200, page([org(1)], number=1)), (200, page([org(2)], number=2)))
    result = run(conn, segment, fake, pages=5, cap=2)
    assert fake.pages_requested() == [1, 2]
    assert result.stopped_by_cap is True
    assert db.usage_this_month(conn, "apollo", "credits") == 2

    again = FakeApollo()
    assert run(conn, segment, again, cap=2).stopped_by_cap is True
    assert again.requests == []


def test_last_page_marks_segment_exhausted(conn: sqlite3.Connection, segment: Segment) -> None:
    result = run(conn, segment, FakeApollo((200, page([org(1)], number=1, total_pages=1))), pages=3)
    assert result.exhausted is True and result.pages == 1

    fake = FakeApollo()
    later = run(conn, segment, fake)
    assert later.exhausted is True and fake.requests == []
    assert "no more pages" in source.describe(conn, segment, pages=1, cap=10)


def test_error_keeps_earlier_pages(conn: sqlite3.Connection, segment: Segment) -> None:
    fake = FakeApollo((200, page([org(1)], number=1)), (401, {"error": "bad key"}))
    result = run(conn, segment, fake, pages=3)
    assert result.pages == 1 and result.saved == 1
    assert "rejected the API key" in (result.error or "")
    assert db.usage_this_month(conn, "apollo", "credits") == 1
    assert source.start_point(conn, segment)[0] == 2


def test_summary_text(conn: sqlite3.Connection, segment: Segment) -> None:
    result = run(conn, segment, FakeApollo((200, page([org(1), org(2, "", website_url=None)]))))
    text = source.summarize(result, used=1, cap=10)
    assert "saved (new)          1" in text
    assert "no website           1" in text
    assert "about 500 matching companies" in text
    assert "Next run continues at page 2." in text
