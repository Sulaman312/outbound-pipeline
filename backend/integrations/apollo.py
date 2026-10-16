"""Apollo API, limited to Organization Search (finding companies).

The team's key is a master key, which could do anything on the Apollo account, so this module
refuses every path that isn't on ALLOWED_PATHS.
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.http import HttpError, send

BASE_URL = "https://api.apollo.io"
ORG_SEARCH_PATH = "/api/v1/mixed_companies/search"
ALLOWED_PATHS = frozenset({ORG_SEARCH_PATH})

CREDITS_PER_PAGE = 1  # Apollo: Organization Search costs 1 credit per page
MAX_PER_PAGE = 100
MAX_PAGE = 500  # Apollo shows at most 50,000 records per search (100 x 500)

# The job-post signal (job titles, posted in the last N days) is stored on ICPs but not sent:
# Apollo's parameter names for it are unconfirmed (docs/research.md, section 1). Until they are,
# sourcing an ICP with a signal is refused rather than run without it.
JOB_SIGNAL_CONFIRMED = False
SIGNAL_FIELDS = ("job_titles", "job_posted_within_days")


class ApolloError(Exception):
    """Apollo said no, or couldn't be reached. The message says what to do."""


def has_signal(settings: dict[str, Any]) -> bool:
    return any(settings.get(name) for name in SIGNAL_FIELDS)


def search_params(
    settings: dict[str, Any], page: int, per_page: int = MAX_PER_PAGE
) -> list[tuple[str, str]]:
    """The query parameters for one page of an ICP's search (its Apollo settings)."""
    params = [("page", str(page)), ("per_page", str(per_page))]
    params += [("organization_num_employees_ranges[]", r) for r in settings["employee_ranges"]]
    params += [("organization_locations[]", loc) for loc in settings["hq_locations"]]
    params += [("q_organization_keyword_tags[]", k) for k in settings.get("keywords", [])]
    return params


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        detail = (
            str(body.get("error") or body.get("message") or body)
            if isinstance(body, dict)
            else str(body)
        )
    except ValueError:
        detail = response.text
    detail = detail.strip()[:300]
    status = response.status_code
    if status == 401:
        return "Apollo rejected the API key (401). Check APOLLO_API_KEY in .env."
    if status == 403:
        return (
            "Apollo refused Organization Search (403). The plan or key doesn't allow it. "
            "If the key isn't a master key, tick api/v1/mixed_companies/search on it. "
            f"Apollo said: {detail}"
        )
    if status == 422:
        return f"Apollo didn't accept the search filters (422). Apollo said: {detail}"
    if status == 429:
        return "Apollo's rate limit was hit (429) and retries ran out. Wait a minute and try again."
    return f"Apollo error {status}. Apollo said: {detail}"


def _post(
    client: httpx.Client, api_key: str, path: str, params: list[tuple[str, str]]
) -> dict[str, Any]:
    if path not in ALLOWED_PATHS:
        raise ApolloError(f"refusing to call {path}: it isn't on the allowed list")
    headers = {
        "x-api-key": api_key,  # in the header, never in the URL
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Cache-Control": "no-cache",
    }
    try:
        response = send(client, "POST", BASE_URL + path, headers=headers, params=params, json={})
    except HttpError as exc:
        raise ApolloError(f"couldn't reach Apollo: {exc}") from exc
    if response.status_code != 200:
        raise ApolloError(_error_message(response))
    try:
        data = response.json()
    except ValueError as exc:
        raise ApolloError("Apollo sent back something that isn't JSON") from exc
    if not isinstance(data, dict):
        raise ApolloError("Apollo sent back an unexpected response shape")
    return data


def search_companies(
    client: httpx.Client,
    api_key: str,
    settings: dict[str, Any],
    page: int,
    per_page: int = MAX_PER_PAGE,
) -> dict[str, Any]:
    """Fetch one page of companies for an ICP's Apollo settings. Costs 1 Apollo credit."""
    return _post(client, api_key, ORG_SEARCH_PATH, search_params(settings, page, per_page))


def companies_in(data: dict[str, Any]) -> list[dict[str, Any]]:
    """All company records on a page. Apollo splits them into new ones and ones already saved."""
    found: list[dict[str, Any]] = []
    for key in ("organizations", "accounts"):
        found += [item for item in (data.get(key) or []) if isinstance(item, dict)]
    return found


def pagination(data: dict[str, Any]) -> tuple[int | None, int | None]:
    """(total matching companies, total pages) as Apollo reports them."""
    info = data.get("pagination") or {}
    total = info.get("total_entries")
    pages = info.get("total_pages")
    return (total if isinstance(total, int) else None, pages if isinstance(pages, int) else None)


def to_company(record: dict[str, Any]) -> dict[str, Any]:
    """Map one Apollo record to our company fields. The domain isn't normalized yet.

    Organization Search sends no headcount, location or industry (checked on real data,
    2026-10-15), so those columns stay empty until the email step fills them.
    """
    return {
        "source": "apollo",
        # saved accounts carry the organization id separately from their own id
        "source_id": str(record.get("organization_id") or record.get("id") or ""),
        "name": record.get("name"),
        "website": record.get("primary_domain")
        or record.get("domain")
        or record.get("website_url"),
        "linkedin_url": record.get("linkedin_url"),
    }
