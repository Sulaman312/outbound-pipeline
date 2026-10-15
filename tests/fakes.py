"""Fake Apollo responses and a fake transport for tests. Nothing here uses the network."""

from __future__ import annotations

import json
from typing import Any

import httpx


def org(number: int, domain: str | None = None, **fields: Any) -> dict[str, Any]:
    """One Apollo organization record, the way Organization Search returns it."""
    record: dict[str, Any] = {
        "id": f"org{number}",
        "name": f"Company {number}",
        "primary_domain": domain if domain is not None else f"company{number}.com",
        "website_url": f"http://www.company{number}.com",
        "city": "Austin",
        "state": "Texas",
        "country": "United States",
        "estimated_num_employees": 8,
        "industry": "accounting",
        "linkedin_url": f"http://www.linkedin.com/company/company{number}",
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


def no_network_client() -> httpx.Client:
    """A client that fails the test if anything tries to send a request."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network used in a test that must not: {request.url}")

    return httpx.Client(transport=httpx.MockTransport(refuse))
