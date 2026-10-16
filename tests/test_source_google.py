"""stages/source.py with Google Maps: searches, page tokens, caps, skips, duplicates and chains."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import FakeApollo, FakeGoogle, icp_data, maps_settings, org, page, place, places_page

from backend import db, icps
from backend.db import Connection
from backend.icps import Icp
from backend.stages import source


@pytest.fixture
def conn(project: Path) -> Connection:
    connection = db.connect(project)
    yield connection
    connection.close()


def make_icp(conn: Connection, key: str = "vets_us", **settings: object) -> Icp:
    return icps.create(conn, icp_data(key, sources={"google_maps": maps_settings(**settings)}))


def run(conn: Connection, icp: Icp, fake: FakeGoogle, cap: int = 5) -> source.SourceResult:
    return source.run_live(
        conn, icp, "google_maps", client=fake.client(), api_key="key", cap=cap, pages=1
    )


def used(conn: Connection) -> int:
    return db.usage_this_month(conn, "google_places", "requests")


def test_preview_lists_every_search_and_its_cost(conn: Connection) -> None:
    icp = make_icp(conn, queries=["vet clinic", "animal hospital"], cities=["Austin, TX", "Dallas, TX"],
                   pages_per_query=2, place_type="veterinary_care")  # fmt: skip
    text = source.describe(conn, icp, "google_maps", pages=1, cap=5)
    assert "POST https://places.googleapis.com/v1/places:searchText" in text
    assert "place type: veterinary_care (strict)" in text
    assert "2 phrase(s) x 2 city(ies) = 4" in text
    for query in ("vet clinic in Austin, TX", "vet clinic in Dallas, TX",
                  "animal hospital in Austin, TX", "animal hospital in Dallas, TX"):  # fmt: skip
        assert f"{query}  ->  2 request(s)" in text
    assert "up to 8 Google request(s)" in text
    assert "0 of 5 requests used" in text and "room for only 5" in text
    assert source.credits_for(conn, icp, "google_maps", 1) == 8


def test_run_saves_usable_places_and_skips_the_rest(conn: Connection) -> None:
    with conn:
        db.add_suppression(conn, "blocked.com", "domain", "client")
    icp = make_icp(conn)
    places = [
        place(1, website="https://www.Clinic-One.com/book?x=1"),
        place(2, website=None),  # no website
        place(3, businessStatus="CLOSED_PERMANENTLY"),
        place(4, website="http://blocked.com"),
        place(5, website="https://clinic-one.com"),  # same company, another place
    ]
    fake = FakeGoogle((200, places_page(places)))
    result = run(conn, icp, fake)
    assert (result.seen, result.saved, result.no_domain, result.closed, result.suppressed,
            result.duplicate) == (5, 1, 1, 1, 1, 1)  # fmt: skip
    assert result.credits == 1 and used(conn) == 1
    [company] = db.list_companies(conn)
    assert (company["domain"], company["source"], company["source_id"], company["icp"]) == (
        "clinic-one.com", "google_places", "place1", "vets_us",
    )  # fmt: skip
    assert (company["city"], company["state"], company["country"]) == ("Austin", "TX", "US")
    assert set(json.loads(company["raw"])) <= {
        "id", "displayName", "websiteUri", "formattedAddress", "addressComponents",
        "nationalPhoneNumber", "types", "primaryType", "businessStatus",
    }  # fmt: skip
    summary = source.summarize(result, used=1, cap=5)
    for line in ("found                5", "saved (new)          1", "no website           1",
                 "closed               1", "likely chains        0", "do-not-contact       1",
                 "already saved        1"):  # fmt: skip
        assert line in summary


def test_page_tokens_and_a_rerun_never_pays_twice(conn: Connection) -> None:
    icp = make_icp(conn, pages_per_query=2)
    fake = FakeGoogle((200, places_page([place(1)], "t2")), (200, places_page([place(2)], "t3")))
    result = run(conn, icp, fake)
    assert result.pages == 2 and result.saved == 2 and used(conn) == 2
    first, second = fake.bodies()
    assert "pageToken" not in first and second["pageToken"] == "t2"
    assert {k: v for k, v in second.items() if k != "pageToken"} == first  # same parameters

    again = FakeGoogle()
    later = run(conn, icp, again)  # nothing left: no request, nothing spent
    assert again.requests == [] and later.pages == 0 and used(conn) == 2
    assert "Nothing left to fetch from Google Maps" in source.summarize(later, used=2, cap=5)

    more = icps.update(
        conn, icp.key, icp_data(icp.key, sources={"google_maps": maps_settings(pages_per_query=3)})
    )
    third = FakeGoogle((200, places_page([place(3)])))
    run(conn, more, third)  # continues with the saved token, page 3 only
    assert third.bodies()[0]["pageToken"] == "t3" and used(conn) == 3


def test_last_page_ends_the_search(conn: Connection) -> None:
    icp = make_icp(conn, pages_per_query=3)
    fake = FakeGoogle((200, places_page([place(1)])))  # no next token
    result = run(conn, icp, fake)
    assert len(fake.requests) == 1 and result.exhausted
    assert "Every search is done." in source.summarize(result, used=1, cap=5)


def test_changing_region_or_type_starts_again(conn: Connection) -> None:
    icp = make_icp(conn)
    run(conn, icp, FakeGoogle((200, places_page([place(1)], "t2"))))
    changed = icps.update(
        conn, icp.key, icp_data(icp.key, sources={"google_maps": maps_settings(region_code="ca")})
    )
    fake = FakeGoogle((200, places_page([])))
    run(conn, changed, fake)
    assert "pageToken" not in fake.bodies()[0] and fake.bodies()[0]["regionCode"] == "ca"


def test_cap_is_reserved_before_each_request(conn: Connection) -> None:
    icp = make_icp(conn, queries=["a", "b", "c"], cities=["X", "Y"])  # 6 searches
    fake = FakeGoogle(*[(200, places_page([place(i)])) for i in range(1, 6)])
    result = run(conn, icp, fake, cap=5)
    assert len(fake.requests) == 5 and result.stopped_by_cap and used(conn) == 5
    assert "the monthly Google Maps cap (5 requests) is reached" in source.summarize(
        result, used=5, cap=5
    )
    assert "caps.google_places.requests" in source.summarize(result, used=5, cap=5)
    nothing = FakeGoogle()
    assert run(conn, icp, nothing, cap=5).stopped_by_cap and nothing.requests == []


def test_error_keeps_the_reservation(conn: Connection) -> None:
    icp = make_icp(conn)
    fake = FakeGoogle((403, {"error": {"code": 403, "message": "x",
                                       "details": [{"reason": "BILLING_DISABLED"}]}}))  # fmt: skip
    result = run(conn, icp, fake)
    assert "billing is off" in (result.error or "") and used(conn) == 1


def test_expired_page_token_marks_the_search_done(conn: Connection) -> None:
    icp = make_icp(conn, pages_per_query=1)
    run(conn, icp, FakeGoogle((200, places_page([place(1)], "old-token"))))
    more = icps.update(
        conn, icp.key, icp_data(icp.key, sources={"google_maps": maps_settings(pages_per_query=2)})
    )
    fake = FakeGoogle((400, {"error": {"code": 400, "message": "Invalid page token"}}))
    result = run(conn, more, fake)
    assert "token expired" in (result.error or "")
    assert source.credits_for(conn, more, "google_maps", 1) == 0  # never retried


def test_duplicates_across_apollo_and_google(conn: Connection) -> None:
    apollo_icp = icps.create(conn, icp_data("from_apollo"))
    source.run_live(conn, apollo_icp, "apollo", client=FakeApollo((200, page([org(1)]))).client(),
                    api_key="k", cap=10, pages=1)  # fmt: skip
    icp = make_icp(conn)
    result = run(
        conn, icp, FakeGoogle((200, places_page([place(9, website="https://company1.com")])))
    )
    assert (result.saved, result.duplicate) == (0, 1)
    [company] = db.list_companies(conn)
    assert (company["source"], company["icp"]) == ("apollo", "from_apollo")


def test_same_place_again_is_a_duplicate(conn: Connection) -> None:
    icp = make_icp(conn, queries=["vets", "vet clinic"])  # two searches find the same place
    fake = FakeGoogle((200, places_page([place(1)])), (200, places_page([place(1)])))
    result = run(conn, icp, fake)
    assert (result.saved, result.duplicate, result.chains) == (1, 1, 0)


def test_chain_is_skipped_and_held_back_from_clay(conn: Connection) -> None:
    icp = make_icp(conn)
    branches = [
        place(i, website="https://www.bigchain.com/location/" + str(i)) for i in (1, 2, 3, 4)
    ]
    result = run(conn, icp, FakeGoogle((200, places_page([*branches, place(5)]))))
    assert (result.saved, result.duplicate, result.chains) == (2, 1, 2)
    rows = {r["domain"]: r for r in db.list_companies(conn)}
    assert rows["bigchain.com"]["likely_chain"] == 1 and rows["bigchain.com"]["status"] == "chain"
    assert rows["clinic5.com"]["likely_chain"] == 0
    assert db.count_waiting_for_clay(conn) == 1  # the chain never goes to Clay


def test_chain_is_kept_and_marked_when_skip_is_off(conn: Connection) -> None:
    icp = make_icp(conn, skip_chains=False)
    branches = [place(i, website="https://bigchain.com") for i in (1, 2, 3)]
    result = run(conn, icp, FakeGoogle((200, places_page(branches))))
    assert (result.saved, result.duplicate, result.chains) == (1, 2, 1)
    [row] = db.list_companies(conn)
    assert row["likely_chain"] == 1 and row["status"] == "new"
