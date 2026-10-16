"""integrations/google_places.py: the request we send, the allow-list, errors, and reading places."""

from __future__ import annotations

from functools import partial

import pytest
from fakes import FakeGoogle, place, places_page

from backend import http
from backend.integrations import google_places

EXPECTED_MASK = (
    "places.id,places.displayName,places.websiteUri,places.formattedAddress,"
    "places.addressComponents,places.nationalPhoneNumber,places.types,places.primaryType,"
    "places.businessStatus,nextPageToken"
)


def test_request_shape_field_mask_and_key_in_header_only() -> None:
    fake = FakeGoogle((200, places_page([place(1)])))
    google_places.search_text(fake.client(), "secret-123", "vet clinic in Austin, TX", "us")
    request = fake.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://places.googleapis.com/v1/places:searchText"
    assert request.headers["X-Goog-Api-Key"] == "secret-123"
    assert request.headers["X-Goog-FieldMask"] == EXPECTED_MASK
    assert "secret-123" not in str(request.url)
    assert "reviews" not in EXPECTED_MASK and "photos" not in EXPECTED_MASK
    assert fake.bodies() == [
        {
            "textQuery": "vet clinic in Austin, TX",
            "regionCode": "us",
            "languageCode": "en",
            "pageSize": 20,
        }
    ]


def test_place_type_and_page_token_are_sent() -> None:
    fake = FakeGoogle((200, places_page([])))
    google_places.search_text(
        fake.client(), "key", "vets in Austin", "us", "veterinary_care", "token-2"
    )
    assert fake.bodies()[0] == {
        "textQuery": "vets in Austin",
        "regionCode": "us",
        "languageCode": "en",
        "pageSize": 20,
        "includedType": "veterinary_care",
        "strictTypeFiltering": True,
        "pageToken": "token-2",
    }


def test_only_allowed_paths() -> None:
    fake = FakeGoogle()
    with pytest.raises(google_places.GooglePlacesError, match="allowed list"):
        google_places._post(fake.client(), "key", "/v1/places/abc", {})
    assert fake.requests == []


def _error(status: int, reason: str = "", message: str = "nope") -> tuple[int, dict]:
    details = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}]
    return status, {
        "error": {"code": status, "message": message, "details": details if reason else []}
    }


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_error(403, "SERVICE_DISABLED"), "Places API \\(New\\) isn't enabled"),
        (_error(403, "BILLING_DISABLED"), "billing is off"),
        (_error(403, "API_KEY_SERVICE_BLOCKED"), "tick Places API \\(New\\)"),
        (_error(403, "API_KEY_IP_ADDRESS_BLOCKED"), "certain IP addresses"),
        (_error(400, "API_KEY_INVALID"), "doesn't recognise the key"),
        (_error(403, "", "Permission denied"), "Check that Places API \\(New\\) is enabled"),
        (_error(400, "", "Invalid page token"), "didn't accept the search \\(400\\)"),
        (_error(500, "", "boom"), "Google error 500"),
    ],
)
def test_error_messages(
    response: tuple[int, dict], message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(google_places, "send", partial(http.send, sleep=lambda seconds: None))
    fake = FakeGoogle(*([response] * (4 if response[0] == 500 else 1)))  # 500s are retried
    with pytest.raises(google_places.GooglePlacesError, match=message) as info:
        google_places.search_text(fake.client(), "secret-123", "vets", "us")
    assert "secret-123" not in str(info.value)
    assert info.value.status == response[0]


def test_429_is_retried_then_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr(google_places, "send", partial(http.send, sleep=waits.append))
    fake = FakeGoogle(*([_error(429)] * 4))
    with pytest.raises(google_places.GooglePlacesError, match="rate limit"):
        google_places.search_text(fake.client(), "key", "vets", "us")
    assert len(fake.requests) == 4 and len(waits) == 3


def test_reading_a_page() -> None:
    data = places_page([place(1), "junk", place(2)], next_token="next")  # type: ignore[list-item]
    assert [p["id"] for p in google_places.places_in(data)] == ["place1", "place2"]
    assert google_places.next_page_token(data) == "next"
    assert google_places.next_page_token(places_page([])) is None


def test_to_company_reads_the_address() -> None:
    assert google_places.to_company(place(7)) == {
        "source": "google_places",
        "source_id": "place7",
        "name": "Clinic 7",
        "website": "https://www.clinic7.com/",
        "city": "Austin",
        "state": "TX",
        "country": "US",
        "industry": "veterinary_care",
    }


def test_kept_fields_drops_anything_we_did_not_ask_for() -> None:
    raw = place(1, reviews=[{"text": "great"}], photos=[{"name": "p"}])
    kept = google_places.kept_fields(raw)
    assert set(kept) <= set(google_places.FIELDS)
    assert "reviews" not in kept and "photos" not in kept


@pytest.mark.parametrize(
    ("status", "open_"),
    [
        ("OPERATIONAL", True),
        ("CLOSED_TEMPORARILY", False),
        ("CLOSED_PERMANENTLY", False),
        (None, False),
    ],
)
def test_only_operational_places_count(status: str | None, open_: bool) -> None:
    record = place(1, businessStatus=status)
    if status is None:
        del record["businessStatus"]
    assert google_places.is_operational(record) is open_
