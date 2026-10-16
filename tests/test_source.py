"""stages/source.py: dry run, filtering, saving, caps, ICPs, and resuming where a run stopped."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import FakeApollo, icp_data, org, page

from backend import db, icps
from backend.db import Connection
from backend.icps import Icp
from backend.integrations import apollo
from backend.stages import source


@pytest.fixture
def conn(project: Path) -> Connection:
    connection = db.connect(project)
    yield connection
    connection.close()


@pytest.fixture
def segment(conn: Connection) -> Icp:
    return icps.create(conn, icp_data())


def run(
    conn: Connection, icp: Icp, fake: FakeApollo, *, pages: int = 1, cap: int = 10
) -> source.SourceResult:
    return source.run_live(
        conn, icp, "apollo", client=fake.client(), api_key="key", cap=cap, pages=pages
    )


def test_dry_run_describes_without_network(conn: Connection, segment: Icp) -> None:
    text = source.describe(conn, segment, "apollo", pages=2, cap=10)
    assert "request:  POST https://api.apollo.io/api/v1/mixed_companies/search" in text
    assert "q_organization_keyword_tags[] = accounting" in text
    assert "pages:    1 to 2" in text
    assert "up to 2 Apollo credit(s)" in text
    assert "0 of 10 credits used" in text


def test_dry_run_warns_when_cap_is_too_small(conn: Connection, segment: Icp) -> None:
    assert "room for only 1 page" in source.describe(conn, segment, "apollo", pages=3, cap=1)


def test_live_run_filters_and_saves(conn: Connection, segment: Icp) -> None:
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
    assert (saved["icp"], saved["source"], saved["source_id"]) == (
        "test_accounting",
        "apollo",
        "org1",
    )
    assert saved["linkedin_url"] == "http://www.linkedin.com/company/company1"
    assert json.loads(saved["raw"])["id"] == "org1"


def test_record_without_primary_domain_uses_website(conn: Connection, segment: Icp) -> None:
    fake = FakeApollo(
        (200, page([org(1, primary_domain=None, website_url="http://www.fallback.io")]))
    )
    run(conn, segment, fake)
    assert [row["domain"] for row in db.list_companies(conn)] == ["fallback.io"]


def test_next_run_continues_at_next_page(conn: Connection, segment: Icp) -> None:
    run(conn, segment, FakeApollo((200, page([org(1)], number=1))))
    fake = FakeApollo((200, page([org(2)], number=2)))
    result = run(conn, segment, fake)
    assert fake.pages_requested() == [2]
    assert result.next_page == 3


def test_changed_filters_start_again_at_page_one(conn: Connection, segment: Icp) -> None:
    run(conn, segment, FakeApollo((200, page([org(1)]))))
    changed = icps.update(
        conn,
        segment.key,
        icp_data(sources={"apollo": {**segment.sources["apollo"], "keywords": ["tax"]}}),
    )
    fake = FakeApollo((200, page([org(2)])))
    run(conn, changed, fake)
    assert fake.pages_requested() == [1]


def test_cap_stops_before_spending(conn: Connection, segment: Icp) -> None:
    fake = FakeApollo((200, page([org(1)], number=1)), (200, page([org(2)], number=2)))
    result = run(conn, segment, fake, pages=5, cap=2)
    assert fake.pages_requested() == [1, 2]
    assert result.stopped_by_cap is True
    assert db.usage_this_month(conn, "apollo", "credits") == 2

    again = FakeApollo()
    assert run(conn, segment, again, cap=2).stopped_by_cap is True
    assert again.requests == []


def test_last_page_marks_segment_exhausted(conn: Connection, segment: Icp) -> None:
    result = run(conn, segment, FakeApollo((200, page([org(1)], number=1, total_pages=1))), pages=3)
    assert result.exhausted is True and result.pages == 1

    fake = FakeApollo()
    later = run(conn, segment, fake)
    assert later.exhausted is True and fake.requests == []
    assert "no more pages" in source.describe(conn, segment, "apollo", pages=1, cap=10)


def test_error_keeps_reservation(conn: Connection, segment: Icp) -> None:
    fake = FakeApollo((200, page([org(1)], number=1)), (401, {"error": "bad key"}))
    result = run(conn, segment, fake, pages=3)
    assert result.pages == 1 and result.saved == 1
    assert "rejected the API key" in (result.error or "")
    # First page succeeded (1), second page reserved then failed (still 2).
    assert db.usage_this_month(conn, "apollo", "credits") == 2
    assert source.start_point(conn, segment, "apollo")[0] == 2


def test_summary_text(conn: Connection, segment: Icp) -> None:
    result = run(conn, segment, FakeApollo((200, page([org(1), org(2, "", website_url=None)]))))
    text = source.summarize(result, used=1, cap=10)
    assert "saved (new)          1" in text
    assert "no website           1" in text
    assert "about 500 matching companies" in text
    assert "Next run continues at page 2." in text


def test_signal_then_pain_keeps_each_company_once(conn: Connection) -> None:
    """The narrow ICP runs first; its twin without the signal skips companies already saved."""
    signal = icps.create(conn, icp_data("dev_signal"))
    pain = icps.create(conn, icp_data("dev_pain"))
    run(conn, signal, FakeApollo((200, page([org(1), org(2)]))))
    result = run(conn, pain, FakeApollo((200, page([org(2), org(3)]))))
    assert (result.saved, result.duplicate) == (1, 1)
    owners = {row["domain"]: row["icp"] for row in db.list_companies(conn)}
    assert owners == {
        "company1.com": "dev_signal",
        "company2.com": "dev_signal",
        "company3.com": "dev_pain",
    }


def test_progress_is_kept_per_icp(conn: Connection) -> None:
    first = icps.create(conn, icp_data("first"))
    second = icps.create(conn, icp_data("second"))
    run(conn, first, FakeApollo((200, page([org(1)], number=1))))
    fake = FakeApollo((200, page([org(2)], number=1)))
    run(conn, second, fake)
    assert fake.pages_requested() == [1]


def test_unconfirmed_signal_is_refused_before_any_request(conn: Connection) -> None:
    settings = {**icp_data()["sources"]["apollo"], "job_titles": ["developer"]}
    icp = icps.create(conn, icp_data("hiring", sources={"apollo": settings}))
    assert apollo.JOB_SIGNAL_CONFIRMED is False
    assert "job-post signal" in (source.icp_problem(icp, "apollo") or "")
    fake = FakeApollo()
    with pytest.raises(ValueError, match="job-post signal"):
        run(conn, icp, fake)
    assert fake.requests == []
    preview = source.describe(conn, icp, "apollo", pages=1, cap=10)
    assert "job titles developer" in preview and "NOT SENT" in preview
    assert "can't run:" in preview


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"active": False}, "inactive"),
        ({"sources": {}}, "has no Apollo settings"),
    ],
)
def test_icp_that_cant_run(conn: Connection, change: dict, message: str) -> None:
    icp = icps.create(conn, icp_data(**change))
    assert message in (source.icp_problem(icp, "apollo") or "")
    assert message in source.describe(conn, icp, "apollo", pages=1, cap=10)


def test_source_the_icp_has_no_settings_for(conn: Connection, segment: Icp) -> None:
    assert "has no Google Maps settings" in (source.icp_problem(segment, "google_maps") or "")
    assert "no source called" in (source.icp_problem(segment, "nope") or "")


def test_old_segment_progress_carries_over(conn: Connection) -> None:
    """Progress saved before ICPs (same filters) still continues at its next page."""
    imported = icps.get(conn, "ai_accounting")
    assert imported is not None and not imported.active
    import hashlib
    import json as _json

    old_hash = hashlib.sha256(
        _json.dumps([["1,20"], ["United States"], ["accounting", "bookkeeping"]]).encode()
    ).hexdigest()[:16]
    assert source.filters_hash("apollo", imported.sources["apollo"]) == old_hash
