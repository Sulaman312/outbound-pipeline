import pytest

from outbound.errors import BudgetExceededError, ProviderError
from outbound.http import current_month
from outbound.sources import build_source
from outbound.sources.apollo import SEARCH_PATH as APOLLO
from outbound.sources.google_places import FIELD_MASK
from outbound.sources.google_places import SEARCH_PATH as PLACES
from tests.conftest import FakeApi


def apollo_person(pid, org_name, domain=None, employees=5, **extra):
    org = {"name": org_name, "estimated_num_employees": employees}
    if domain:
        org["primary_domain"] = domain
    return {"id": pid, "first_name": "Sam", "title": "Founder", "organization": org, **extra}


def place(pid, name, website="https://www.example.com", status="OPERATIONAL"):
    return {
        "id": pid,
        "displayName": {"text": name},
        "websiteUri": website,
        "nationalPhoneNumber": "020 1234",
        "businessStatus": status,
    }


def test_dry_run_cannot_reach_network(config, store):
    src = build_source("apollo", config, store, live=False)
    icp, country = config.icp("A"), config.country("US")
    plans = src.plan(src.parse_options(icp), icp, country)
    assert plans[0].body["organization_locations"] == ["United States"]
    assert plans[0].body["organization_num_employees_ranges"] == ["1,10"]
    with pytest.raises(RuntimeError, match="Dry run"):
        list(src.fetch(src.parse_options(icp), icp, country))


def test_apollo_request_and_mapping(config, store, keys):
    api = FakeApi(
        {
            APOLLO: [
                (
                    200,
                    {
                        "people": [
                            apollo_person(
                                "p1", "Acme Ltd", "acme.io", last_name_obfuscated="Sm***h"
                            ),
                            {"id": "p2"},
                        ],  # no company: skipped
                        "pagination": {"total_pages": 1},
                    },
                )
            ]
        }
    )
    src = build_source("apollo", config, store, live=True, transport=api)
    icp, country = config.icp("A"), config.country("UK")
    records = list(src.fetch(src.parse_options(icp), icp, country))

    req = api.requests[0]
    assert req.headers["X-Api-Key"] == "test-apollo"
    assert api.bodies()[0]["organization_locations"] == ["United Kingdom"]
    assert len(records) == 1
    r = records[0]
    assert (r.company.domain, r.company.country, r.company.employees) == ("acme.io", "UK", 5)
    assert r.contact.first_name == "Sam" and r.contact.last_name is None
    assert r.raw["last_name_obfuscated"] == "Sm***h"  # kept for later


def test_apollo_paginates_until_last_page(config, store, keys):
    page = lambda n, total: (
        200,
        {
            "people": [apollo_person(f"p{n}", f"Co{n}", f"co{n}.com")],
            "pagination": {"total_pages": total},
        },
    )
    api = FakeApi({APOLLO: [page(1, 2), page(2, 2)]})
    src = build_source("apollo", config, store, live=True, transport=api)
    icp = config.icp("A")  # max_pages: 2
    records = list(src.fetch(src.parse_options(icp), icp, config.country("US")))
    assert [b["page"] for b in api.bodies()] == [1, 2]
    assert len(records) == 2


def test_places_field_mask_pagination_and_filters(config, store, keys):
    icp = config.icp("B")
    icp.sources["google_places"].update(
        enabled=True, queries=["dentist"], max_pages=2, cities={"AU": ["Sydney"]}
    )
    api = FakeApi(
        {
            PLACES: [
                (
                    200,
                    {
                        "places": [
                            place("a", "Smile Dental"),
                            place("b", "Closed Dental", status="CLOSED_PERMANENTLY"),
                            place("c", "FB Only Dental", website="https://facebook.com/x"),
                        ],
                        "nextPageToken": "t2",
                    },
                ),
                (200, {"places": [place("d", "Harbour Dental", "https://harbourdental.com.au")]}),
            ]
        }
    )
    src = build_source("google_places", config, store, live=True, transport=api)
    records = list(src.fetch(src.parse_options(icp), icp, config.country("AU")))

    assert api.requests[0].headers["X-Goog-FieldMask"] == FIELD_MASK
    assert api.requests[0].headers["X-Goog-Api-Key"] == "test-places"
    bodies = api.bodies()
    assert bodies[0]["textQuery"] == "dentist in Sydney" and bodies[0]["regionCode"] == "AU"
    assert bodies[1]["pageToken"] == "t2"
    assert [r.company.name for r in records] == ["Smile Dental", "Harbour Dental"]


def test_monthly_cap_blocks_the_next_request(config, store, keys):
    config.settings.providers["google_places"].monthly_request_cap = 3
    store.add_usage("google_places", current_month(), 3)
    icp = config.icp("B")
    icp.sources["google_places"]["enabled"] = True
    api = FakeApi({})
    src = build_source("google_places", config, store, live=True, transport=api)
    with pytest.raises(BudgetExceededError):
        list(src.fetch(src.parse_options(icp), icp, config.country("US")))
    assert api.requests == []


def test_retries_on_429_then_fails_on_401(config, store, keys):
    config.settings.http.max_retries = 2
    api = FakeApi({APOLLO: [(429, {}), (200, {"people": []}), (401, {"error": "bad key"})]})
    src = build_source("apollo", config, store, live=True, transport=api)
    src.client._sleep = lambda s: None
    icp, country = config.icp("A"), config.country("US")
    assert list(src.fetch(src.parse_options(icp), icp, country)) == []
    assert len(api.requests) == 2
    assert store.usage("apollo", current_month()) == 2  # every sent request is counted
    with pytest.raises(ProviderError, match="401"):
        list(src.fetch(src.parse_options(icp), icp, country))
