"""Find companies for one segment through Apollo and save the new ones.

A dry run (the default) only describes the request and what it could cost. It never touches
the network. A live run fetches one page at a time and stops before the monthly cap. It also
remembers where it stopped, so the next run continues instead of paying for the same page twice.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

import httpx

from outbound import db
from outbound.clients import apollo
from outbound.config import Segment
from outbound.normalize import normalize_domain

PROVIDER, UNIT = "apollo", "credits"


@dataclass
class SourceResult:
    pages: int = 0
    credits: int = 0
    seen: int = 0
    saved: int = 0
    duplicate: int = 0
    no_domain: int = 0
    suppressed: int = 0
    total_entries: int | None = None
    next_page: int = 1
    exhausted: bool = False
    stopped_by_cap: bool = False
    error: str | None = None


def filters_hash(segment: Segment) -> str:
    """Changes whenever the segment's search filters change."""
    text = json.dumps([segment.employees, segment.locations, segment.keywords])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def start_point(conn: sqlite3.Connection, segment: Segment) -> tuple[int, bool, int | None]:
    """(next page, no more pages?, last reported total). Filters changed -> back to page 1."""
    row = db.get_progress(conn, segment.key)
    if row is None or row["filters_hash"] != filters_hash(segment):
        return 1, False, None
    return row["next_page"], bool(row["exhausted"]), row["total_entries"]


def _save(
    conn: sqlite3.Connection, segment: Segment, record: dict[str, Any], result: SourceResult
) -> None:
    """Check one Apollo record and save it if it's usable. Updates the counts in result.

    Apollo's company search sends no headcount or location, so it can't check "US only" or
    "1-20 staff" here. Apollo applies those filters itself. Person enrichment, at the email
    step, returns full company details, and the check runs again there.
    """
    company = apollo.to_company(record)
    domain = normalize_domain(company.pop("website"))
    result.seen += 1
    if not domain:
        result.no_domain += 1
    elif db.is_suppressed(conn, domain):
        result.suppressed += 1
    else:
        company.update(
            domain=domain,
            name=company["name"] or domain,
            source_id=company["source_id"] or domain,
            segment=segment.key,
            raw=json.dumps(record, ensure_ascii=False),
        )
        if db.insert_company(conn, company):
            result.saved += 1
        else:
            result.duplicate += 1


def run_live(
    conn: sqlite3.Connection,
    segment: Segment,
    *,
    client: httpx.Client,
    api_key: str,
    cap: int,
    pages: int,
    per_page: int = apollo.MAX_PER_PAGE,
) -> SourceResult:
    """Fetch up to `pages` pages from Apollo for this segment and save usable companies."""
    result = SourceResult()
    page, exhausted, result.total_entries = start_point(conn, segment)
    result.next_page, result.exhausted = page, exhausted
    if exhausted:
        return result

    fhash = filters_hash(segment)
    for _ in range(pages):
        if db.usage_this_month(conn, PROVIDER, UNIT) + apollo.CREDITS_PER_PAGE > cap:
            result.stopped_by_cap = True
            break
        try:
            data = apollo.search_companies(client, api_key, segment, page, per_page)
        except apollo.ApolloError as exc:
            result.error = str(exc)
            break

        records = apollo.companies_in(data)
        total, total_pages = apollo.pagination(data)
        last = (
            not records
            or page >= apollo.MAX_PAGE
            or (total_pages is not None and page >= total_pages)
            or (total_pages is None and len(records) < per_page)
        )
        with conn:  # one page = one unit of work: credit, companies and progress together
            db.add_usage(conn, PROVIDER, UNIT, apollo.CREDITS_PER_PAGE)
            for record in records:
                _save(conn, segment, record, result)
            db.save_progress(conn, segment.key, fhash, page + 1, total, last)

        result.pages += 1
        result.credits += apollo.CREDITS_PER_PAGE
        if total is not None:
            result.total_entries = total
        page += 1
        result.next_page = page
        if last:
            result.exhausted = True
            break
    return result


def describe(
    conn: sqlite3.Connection,
    segment: Segment,
    *,
    pages: int,
    cap: int | None,
    per_page: int = apollo.MAX_PER_PAGE,
) -> str:
    """What a live run would do (the preview). Reads only the local database."""
    page, exhausted, total = start_point(conn, segment)
    used = db.usage_this_month(conn, PROVIDER, UNIT)
    cost = pages * apollo.CREDITS_PER_PAGE
    lines = [
        f"segment:  {segment.key} ({segment.offer})",
        f"          {segment.description}",
        f"request:  POST {apollo.BASE_URL}{apollo.ORG_SEARCH_PATH}",
        "filters:",
    ]
    for name, value in apollo.search_params(segment, page, per_page)[2:]:
        lines.append(f"          {name} = {value}")
    if exhausted:
        lines.append(
            "status:   no more pages for this segment. Change its filters to search again."
        )
        return "\n".join(lines)
    lines.append(f"pages:    {page} to {page + pages - 1} ({per_page} companies per page)")
    lines.append(f"cost:     up to {cost} Apollo credit(s), 1 per page")
    if cap is None:
        lines.append("budget:   no Apollo cap in config/settings.yaml, so live runs are blocked")
    else:
        lines.append(f"budget:   {used} of {cap} credits used this month ({db.current_month()})")
        if used + cost > cap:
            room = max(cap - used, 0) // apollo.CREDITS_PER_PAGE
            lines.append(f"note:     the cap leaves room for only {room} page(s) this month")
    if total is not None:
        lines.append(f"last run: Apollo reported about {total:,} matching companies")
    return "\n".join(lines)


def summarize(result: SourceResult, *, used: int, cap: int) -> str:
    """The report printed after a live run."""
    if result.pages == 0 and result.exhausted:
        return "No more pages for this segment. Change its filters in config/segments.yaml to search again."
    lines = [
        f"done: {result.pages} page(s), {result.credits} credit(s) "
        f"({used} of {cap} used this month)",
        f"  saved (new)          {result.saved}",
        f"  already saved        {result.duplicate}",
        f"  no website           {result.no_domain}",
        f"  do-not-contact       {result.suppressed}",
    ]
    if result.total_entries is not None:
        lines.append(f"Apollo reports about {result.total_entries:,} matching companies.")
    if result.error:
        lines.append(f"Stopped by an error: {result.error}")
    elif result.stopped_by_cap:
        lines.append(
            f"Stopped: the monthly Apollo cap ({cap} credits) is reached. "
            "Raise caps.apollo.credits in config/settings.yaml to continue."
        )
    elif result.exhausted:
        lines.append("That was the last page for this segment.")
    else:
        lines.append(f"Next run continues at page {result.next_page}.")
    return "\n".join(lines)
