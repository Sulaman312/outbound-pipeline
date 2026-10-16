"""Google Places API (New), limited to Text Search (finding businesses by phrase and city).

Only POST https://places.googleapis.com/v1/places:searchText is allowed. The key goes in the
X-Goog-Api-Key header, never in the URL. The field mask asks for exactly FIELDS (plus the next
page token): never reviews or photos. websiteUri and nationalPhoneNumber make every request a
Text Search Enterprise request (docs/research.md, section 2).
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.http import HttpError, send

BASE_URL = "https://places.googleapis.com"
SEARCH_PATH = "/v1/places:searchText"
ALLOWED_PATHS = frozenset({SEARCH_PATH})

FIELDS = (
    "id",
    "displayName",
    "websiteUri",
    "formattedAddress",
    "addressComponents",
    "nationalPhoneNumber",
    "types",
    "primaryType",
    "businessStatus",
)
FIELD_MASK = ",".join(f"places.{name}" for name in FIELDS) + ",nextPageToken"

PAGE_SIZE = 20  # Google's most per page
MAX_PAGES_PER_QUERY = 3  # Google stops at 60 results per query
REQUESTS_PER_PAGE = 1
LANGUAGE = "en"


class GooglePlacesError(Exception):
    """Google said no, or couldn't be reached. The message says what to do."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status  # the HTTP status, when Google answered


def search_body(
    query: str, region_code: str, place_type: str | None, page_token: str | None
) -> dict[str, Any]:
    """The request body. Every page repeats the same parameters, plus the page token."""
    body: dict[str, Any] = {
        "textQuery": query,
        "regionCode": region_code,
        "languageCode": LANGUAGE,
        "pageSize": PAGE_SIZE,
    }
    if place_type:
        body["includedType"] = place_type
        body["strictTypeFiltering"] = True
    if page_token:
        body["pageToken"] = page_token
    return body


_REASONS = {
    "SERVICE_DISABLED": "Places API (New) isn't enabled on the Google Cloud project. Enable it in "
    "the Cloud Console (APIs & Services).",
    "BILLING_DISABLED": "billing is off on the Google Cloud project. Turn on billing; the first "
    "1,000 Text Search requests a month are still free.",
    "API_KEY_SERVICE_BLOCKED": "the key isn't allowed to call Places API (New). In the Cloud "
    "Console, edit the key's API restrictions and tick Places API (New).",
    "API_KEY_HTTP_REFERRER_BLOCKED": "the key only works from certain websites. Set its "
    "application restriction to None (or IP addresses) for this app.",
    "API_KEY_IP_ADDRESS_BLOCKED": "the key only works from certain IP addresses, and this "
    "computer's isn't one of them. Add it, or remove the IP restriction.",
    "API_KEY_INVALID": "Google doesn't recognise the key. Check GOOGLE_PLACES_API_KEY in .env.",
}


def _error_message(response: httpx.Response) -> str:
    status = response.status_code
    reason, detail = "", ""
    try:
        error = response.json().get("error") or {}
        detail = str(error.get("message") or "")
        for item in error.get("details") or []:
            if isinstance(item, dict) and item.get("reason"):
                reason = str(item["reason"])
                break
    except (ValueError, AttributeError):
        detail = response.text
    detail = detail.strip()[:300]
    if reason in _REASONS:
        return f"Google refused the request ({status}): {_REASONS[reason]}"
    if status == 403:
        return (
            "Google refused the request (403). Check that Places API (New) is enabled, billing "
            "is on, and the key is allowed to call Places API (New). "
            f"Google said: {detail}"
        )
    if status == 429:
        return (
            "Google's rate limit or daily quota was hit (429) and retries ran out. Wait a "
            "minute, or check the quota in the Cloud Console."
        )
    if status == 400:
        return f"Google didn't accept the search (400). Google said: {detail}"
    return f"Google error {status}. Google said: {detail}"


def _post(client: httpx.Client, api_key: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    if path not in ALLOWED_PATHS:
        raise GooglePlacesError(f"refusing to call {path}: it isn't on the allowed list")
    headers = {
        "X-Goog-Api-Key": api_key,  # in the header, never in the URL
        "X-Goog-FieldMask": FIELD_MASK,
        "Content-Type": "application/json",
    }
    try:
        response = send(client, "POST", BASE_URL + path, headers=headers, json=body)
    except HttpError as exc:
        raise GooglePlacesError(f"couldn't reach Google: {exc}") from exc
    if response.status_code != 200:
        raise GooglePlacesError(_error_message(response), response.status_code)
    try:
        data = response.json()
    except ValueError as exc:
        raise GooglePlacesError("Google sent back something that isn't JSON") from exc
    if not isinstance(data, dict):
        raise GooglePlacesError("Google sent back an unexpected response shape")
    return data


def search_text(
    client: httpx.Client,
    api_key: str,
    query: str,
    region_code: str,
    place_type: str | None = None,
    page_token: str | None = None,
) -> dict[str, Any]:
    """One page (up to 20 places) for one query. Counts as 1 Text Search request."""
    return _post(
        client, api_key, SEARCH_PATH, search_body(query, region_code, place_type, page_token)
    )


def places_in(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in (data.get("places") or []) if isinstance(p, dict)]


def next_page_token(data: dict[str, Any]) -> str | None:
    token = data.get("nextPageToken")
    return token if isinstance(token, str) and token else None


def kept_fields(place: dict[str, Any]) -> dict[str, Any]:
    """The place with only the fields we asked for, for the companies table's raw column."""
    return {name: place[name] for name in FIELDS if name in place}


def _component(place: dict[str, Any], kinds: tuple[str, ...], text: str) -> str | None:
    for kind in kinds:
        for part in place.get("addressComponents") or []:
            if isinstance(part, dict) and kind in (part.get("types") or []):
                value = part.get(text) or part.get("longText")
                return str(value) if value else None
    return None


def to_company(place: dict[str, Any]) -> dict[str, Any]:
    """Map one place to our company fields. The domain isn't normalized yet."""
    name = place.get("displayName")
    return {
        "source": "google_places",
        "source_id": str(place.get("id") or ""),
        "name": name.get("text") if isinstance(name, dict) else None,
        "website": place.get("websiteUri"),
        "city": _component(place, ("locality", "postal_town", "sublocality"), "longText"),
        "state": _component(place, ("administrative_area_level_1",), "shortText"),
        "country": _component(place, ("country",), "shortText"),
        "industry": place.get("primaryType"),
    }


def is_operational(place: dict[str, Any]) -> bool:
    """Open for business. Closed (for now or for good), or no status at all, is skipped."""
    return place.get("businessStatus") == "OPERATIONAL"
