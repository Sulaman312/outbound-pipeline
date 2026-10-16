"""clients/apollo.py: the request we send, the allow-list, errors, and reading responses."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest
from fakes import FakeApollo, org, page

from backend import http
from backend.config import Segment, load_segments
from backend.integrations import apollo


@pytest.fixture
def segment(project: Path) -> Segment:
    return load_segments(project)["ai_accounting"]


def test_search_params(segment: Segment) -> None:
    assert apollo.search_params(segment, page=3) == [
        ("page", "3"),
        ("per_page", "100"),
        ("organization_num_employees_ranges[]", "1,20"),
        ("organization_locations[]", "United States"),
        ("q_organization_keyword_tags[]", "accounting"),
        ("q_organization_keyword_tags[]", "bookkeeping"),
    ]


def test_request_shape_and_key_in_header_only(segment: Segment) -> None:
    fake = FakeApollo((200, page([org(1)])))
    apollo.search_companies(fake.client(), "secret-123", segment, page=1)
    request = fake.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v1/mixed_companies/search"
    assert request.headers["x-api-key"] == "secret-123"
    assert "secret-123" not in str(request.url)
    assert request.url.params.get_list("q_organization_keyword_tags[]") == [
        "accounting",
        "bookkeeping",
    ]


def test_only_allowed_paths(segment: Segment) -> None:
    fake = FakeApollo()
    with pytest.raises(apollo.ApolloError, match="allowed list"):
        apollo._post(fake.client(), "key", "/api/v1/people/bulk_match", [])
    assert fake.requests == []


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "rejected the API key"),
        (403, "refused Organization Search"),
        (422, "didn't accept the search filters"),
        (500, "Apollo error 500"),
    ],
)
def test_error_messages(
    segment: Segment, status: int, message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(apollo, "send", partial(http.send, sleep=lambda seconds: None))
    responses = [(status, {"error": "nope"})] * (4 if status == 500 else 1)  # 500s are retried
    fake = FakeApollo(*responses)
    with pytest.raises(apollo.ApolloError, match=message) as info:
        apollo.search_companies(fake.client(), "secret-123", segment, page=1)
    assert "secret-123" not in str(info.value)


def test_companies_in_reads_both_lists() -> None:
    data = {
        "organizations": [org(1)],
        "accounts": [{"id": "acc9", "organization_id": "org9", "domain": "nine.com"}],
    }
    found = apollo.companies_in(data)
    assert len(found) == 2
    assert apollo.to_company(found[1])["source_id"] == "org9"
    assert apollo.to_company(found[1])["website"] == "nine.com"


def test_to_company_maps_only_fields_apollo_sends() -> None:
    company = apollo.to_company(org(1))
    assert company == {
        "source": "apollo",
        "source_id": "org1",
        "name": "Company 1",
        "website": "company1.com",
        "linkedin_url": "http://www.linkedin.com/company/company1",
    }


def test_pagination() -> None:
    assert apollo.pagination(page([], total_pages=4)) == (400, 4)
    assert apollo.pagination({}) == (None, None)
