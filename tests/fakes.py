"""Fake Apollo responses, a fake transport, and test ICPs. Nothing here uses the network."""

from __future__ import annotations

import json
from typing import Any

import httpx


def org(number: int, domain: str | None = None, **fields: Any) -> dict[str, Any]:
    """One Apollo organization record, shaped like real Organization Search output (2026-10-15).

    It has no headcount, location or industry, because Organization Search doesn't send them.
    """
    record: dict[str, Any] = {
        "id": f"org{number}",
        "name": f"Company {number}",
        "primary_domain": domain if domain is not None else f"company{number}.com",
        "website_url": f"http://www.company{number}.com",
        "linkedin_url": f"http://www.linkedin.com/company/company{number}",
        "linkedin_uid": str(1000 + number),
        "phone": "+1 512-555-0100",
        "founded_year": 2015,
        "naics_codes": ["54121"],
        "organization_headcount_twelve_month_growth": 0.1,
    }
    record.update(fields)
    return record


def page(records: list[dict[str, Any]], number: int = 1, total_pages: int = 5) -> dict[str, Any]:
    return {
        "organizations": records,
        "accounts": [],
        "pagination": {
            "page": number,
            "per_page": 100,
            "total_entries": total_pages * 100,
            "total_pages": total_pages,
        },
    }


class FakeApollo:
    """Answers each request with the next queued (status, body) and records what was asked."""

    def __init__(self, *responses: tuple[int, Any]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError(f"unexpected extra request: {request.url}")
        status, body = self.responses.pop(0)
        return httpx.Response(
            status, content=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def pages_requested(self) -> list[int]:
        return [int(r.url.params["page"]) for r in self.requests]

    def bodies(self) -> list[dict[str, Any]]:
        """The JSON body of each request (Google Places sends its search in the body)."""
        return [json.loads(r.content) for r in self.requests]


FakeGoogle = FakeApollo  # same idea: queued answers, recorded requests


def no_network_client() -> httpx.Client:
    """A client that fails the test if anything tries to send a request."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network used in a test that must not: {request.url}")

    return httpx.Client(transport=httpx.MockTransport(refuse))


def place(number: int, website: str | None = "default", **fields: Any) -> dict[str, Any]:
    """One Google place, shaped like Text Search (New) output for our field mask."""
    record: dict[str, Any] = {
        "id": f"place{number}",
        "displayName": {"text": f"Clinic {number}", "languageCode": "en"},
        "websiteUri": f"https://www.clinic{number}.com/" if website == "default" else website,
        "formattedAddress": f"{number} Main St, Austin, TX 78701, USA",
        "addressComponents": [
            {"longText": "Austin", "shortText": "Austin", "types": ["locality", "political"]},
            {"longText": "Texas", "shortText": "TX",
             "types": ["administrative_area_level_1", "political"]},
            {"longText": "United States", "shortText": "US", "types": ["country", "political"]},
        ],
        "nationalPhoneNumber": "(512) 555-0100",
        "types": ["veterinary_care", "point_of_interest", "establishment"],
        "primaryType": "veterinary_care",
        "businessStatus": "OPERATIONAL",
    }  # fmt: skip
    if record["websiteUri"] is None:
        del record["websiteUri"]
    record.update(fields)
    return record


def places_page(places: list[dict[str, Any]], next_token: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"places": places}
    if next_token:
        data["nextPageToken"] = next_token
    return data


def maps_settings(**fields: Any) -> dict[str, Any]:
    """Google Maps settings for an ICP, as the ICPs page would send them."""
    settings: dict[str, Any] = {
        "queries": ["vet clinic"],
        "cities": ["Austin, TX"],
        "region_code": "us",
        "pages_per_query": 1,
    }
    settings.update(fields)
    return settings


def icp_data(key: str = "test_accounting", **fields: Any) -> dict[str, Any]:
    """An active ICP with Apollo settings, as the ICPs page would send it."""
    data: dict[str, Any] = {
        "key": key,
        "name": "US accounting firms",
        "offer": "AI automation",
        "country": "US",
        "person_titles": ["Owner"],
        "sources": {
            "apollo": {
                "hq_locations": ["United States"],
                "employee_ranges": ["1,20"],
                "keywords": ["accounting", "bookkeeping"],
            }
        },
    }
    data.update(fields)
    return data
