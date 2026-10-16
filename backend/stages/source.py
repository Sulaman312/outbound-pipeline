"""Find companies for one ICP from one source, and save the new ones.

Every source saves into the same companies table: one row per domain, ever, and never a
do-not-contact domain. So a company belongs to the first ICP that saves it, and an ICP sourced
later skips it. Run the narrowest ICP (one with a signal) before its broader twin.

A dry run (the default) only describes the request and what it could cost. It never touches
the network. A live run reserves credits under the monthly cap before each call, fetches one
page at a time, and remembers where it stopped per ICP and source, so the next run continues
instead of paying for the same page twice. A failed call keeps its reservation.

Sources that are listed in backend/sources.py but not built yet are refused with a plain message.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx

from backend import db
from backend.db import Connection
from backend.icps import Icp
from backend.integrations import apollo
from backend.normalize import normalize_domain
from backend.sources import BY_KEY

MAX_PAGES_PER_RUN = 50
APOLLO = "apollo"
PROVIDER, UNIT = "apollo", "credits"  # Apollo's monthly usage counter


@dataclass
class SourceResult:
    source: str = APOLLO
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


# --- checks shared by the CLI and the app -------------------------------------------------------


def credits_for(source_key: str, pages: int) -> int:
    """The most a run of `pages` pages from this source can spend."""
    if source_key == APOLLO:
        return pages * apollo.CREDITS_PER_PAGE
    return 0


def pages_problem(pages: int) -> str | None:
    """Why this page count isn't allowed, or None."""
    if not 1 <= pages <= MAX_PAGES_PER_RUN:
        return f"pages must be between 1 and {MAX_PAGES_PER_RUN}"
    return None


def icp_problem(icp: Icp, source_key: str) -> str | None:
    """Why this ICP can't be sourced from this source at all (preview included), or None."""
    source = BY_KEY.get(source_key)
    if source is None:
        return f"there is no source called {source_key!r}"
    if not source.built:
        return f"{source.label} isn't built yet. For now, use another source."
    if not icp.active:
        return f'ICP "{icp.key}" is inactive. Turn it back on on the ICPs page first.'
    settings = icp.sources.get(source_key)
    if not settings:
        return f'ICP "{icp.key}" has no {source.label} settings. Add them on the ICPs page.'
    if source_key == APOLLO and apollo.has_signal(settings) and not apollo.JOB_SIGNAL_CONFIRMED:
        return (
            f'ICP "{icp.key}" has a job-post signal, and Apollo\'s filter names for it are not '
            "confirmed yet, so it can't run without sending the wrong search. Remove the "
            "signal on the ICPs page, or wait until the names are confirmed (docs/research.md)."
        )
    return None


def cap_for(caps: dict[str, dict[str, int]], source_key: str) -> int | None:
    """This source's monthly cap from config/settings.yaml, or None if there isn't one."""
    source = BY_KEY[source_key]
    return caps.get(source.key, {}).get(source.cap_unit)


def live_problem(source_key: str, api_key: str, cap: int | None) -> str | None:
    """Why a live run can't start, or None. The CLI and the app both ask this first."""
    source = BY_KEY[source_key]
    if not api_key:
        return f"{source.key_env} isn't set. Add it to the .env file in the project folder."
    if cap is None:
        return f"set caps.{source.key}.{source.cap_unit} in config/settings.yaml before a live run."
    return None


# --- progress -----------------------------------------------------------------------------------


def filters_hash(source_key: str, settings: dict[str, Any]) -> str:
    """Changes whenever an ICP's search settings for this source change."""
    if source_key == APOLLO:
        # Same shape as before ICPs existed, so saved progress carries over.
        parts: list[Any] = [
            settings["employee_ranges"],
            settings["hq_locations"],
            settings.get("keywords", []),
        ]
        signal = [settings.get(name) for name in apollo.SIGNAL_FIELDS]
        if any(signal):
            parts.append(signal)
    else:
        parts = [settings]
    text = json.dumps(parts, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def start_point(conn: Connection, icp: Icp, source_key: str) -> tuple[int, bool, int | None]:
    """(next page, no more pages?, last reported total). Settings changed -> back to page 1."""
    row = db.get_progress(conn, icp.key, source_key)
    if row is None or row["filters_hash"] != filters_hash(source_key, icp.sources[source_key]):
        return 1, False, None
    return int(row["next_page"]), bool(row["exhausted"]), row["total_entries"]


# --- Apollo -------------------------------------------------------------------------------------


def _save(
    conn: Connection, icp: Icp, company: dict[str, Any], raw: Any, result: SourceResult
) -> None:
    """Check one company and save it if it's usable. Updates the counts in result."""
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
            icp=icp.key,
            raw=json.dumps(raw, ensure_ascii=False),
        )
        if db.insert_company(conn, company):
            result.saved += 1
        else:
            result.duplicate += 1


def _run_apollo(
    conn: Connection,
    icp: Icp,
    *,
    client: httpx.Client,
    api_key: str,
    cap: int,
    pages: int,
    per_page: int,
) -> SourceResult:
    """Apollo's search sends no headcount or location back, so those filters are Apollo's to apply."""
    settings = icp.sources[APOLLO]
    result = SourceResult(source=APOLLO)
    page, exhausted, result.total_entries = start_point(conn, icp, APOLLO)
    result.next_page, result.exhausted = page, exhausted
    if exhausted:
        return result

    fhash = filters_hash(APOLLO, settings)
    for _ in range(pages):
        with conn:
            reserved = db.reserve_usage(conn, PROVIDER, UNIT, apollo.CREDITS_PER_PAGE, cap)
        if not reserved:
            result.stopped_by_cap = True
            break
        try:
            data = apollo.search_companies(client, api_key, settings, page, per_page)
        except apollo.ApolloError as exc:
            # Reservation kept so the cap is never exceeded by retries.
            result.error = str(exc)
            result.credits += apollo.CREDITS_PER_PAGE
            break

        records = apollo.companies_in(data)
        total, total_pages = apollo.pagination(data)
        last = (
            not records
            or page >= apollo.MAX_PAGE
            or (total_pages is not None and page >= total_pages)
            or (total_pages is None and len(records) < per_page)
        )
        with conn:  # companies and progress together; credit already reserved
            for record in records:
                _save(conn, icp, apollo.to_company(record), record, result)
            db.save_progress(conn, icp.key, APOLLO, fhash, page + 1, total, last)

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


def _describe_apollo(
    conn: Connection, icp: Icp, pages: int, cap: int | None, per_page: int
) -> list[str]:
    settings = icp.sources[APOLLO]
    page, exhausted, total = start_point(conn, icp, APOLLO)
    used = db.usage_this_month(conn, PROVIDER, UNIT)
    cost = credits_for(APOLLO, pages)
    lines = [f"request:  POST {apollo.BASE_URL}{apollo.ORG_SEARCH_PATH}", "filters:"]
    for name, value in apollo.search_params(settings, page, per_page)[2:]:
        lines.append(f"          {name} = {value}")
    if apollo.has_signal(settings):
        lines.append(
            "signal:   job titles "
            + ", ".join(settings.get("job_titles", []))
            + (
                f", posted in the last {settings['job_posted_within_days']} days"
                if settings.get("job_posted_within_days")
                else ""
            )
        )
        if not apollo.JOB_SIGNAL_CONFIRMED:
            lines.append("          NOT SENT: Apollo's filter names for it are unconfirmed")
    if exhausted:
        lines.append(
            "status:   no more pages for this ICP. Change its Apollo settings to search again."
        )
        return lines
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
        lines.append(f"pool:     Apollo reported about {total:,} matching companies last time")
    return lines


# --- one entry point per action, whatever the source --------------------------------------------


def describe(
    conn: Connection,
    icp: Icp,
    source_key: str,
    *,
    pages: int,
    cap: int | None,
    per_page: int = apollo.MAX_PER_PAGE,
) -> str:
    """What a live run would do (the preview). Reads only the local database."""
    lines = [f"icp:      {icp.key} ({icp.offer or 'no offer set'})", f"          {icp.name}"]
    if source_key == APOLLO and icp.sources.get(APOLLO):
        lines += _describe_apollo(conn, icp, pages, cap, per_page)
    problem = icp_problem(icp, source_key)
    if problem:
        lines.append(f"can't run: {problem}")
    return "\n".join(lines)


def run_live(
    conn: Connection,
    icp: Icp,
    source_key: str,
    *,
    client: httpx.Client,
    api_key: str,
    cap: int,
    pages: int,
    per_page: int = apollo.MAX_PER_PAGE,
) -> SourceResult:
    """Fetch up to `pages` pages for this ICP from this source and save usable companies."""
    problem = icp_problem(icp, source_key)
    if problem:
        raise ValueError(problem)
    return _run_apollo(
        conn, icp, client=client, api_key=api_key, cap=cap, pages=pages, per_page=per_page
    )


def summarize(result: SourceResult, *, used: int, cap: int) -> str:
    """The report printed after a live run."""
    label = BY_KEY[result.source].label
    if result.pages == 0 and result.exhausted:
        return (
            f"No more {label} pages for this ICP. Change its {label} settings on the ICPs page "
            "to search again."
        )
    lines = [
        f"done: {result.pages} page(s), {result.credits} credit(s) "
        f"({used} of {cap} used this month)",
        f"  saved (new)          {result.saved}",
        f"  already saved        {result.duplicate}   (by this ICP or another one)",
        f"  no website           {result.no_domain}",
        f"  do-not-contact       {result.suppressed}",
    ]
    if result.total_entries is not None:
        lines.append(f"{label} reports about {result.total_entries:,} matching companies.")
    if result.error:
        lines.append(f"Stopped by an error: {result.error}")
    elif result.stopped_by_cap:
        lines.append(
            f"Stopped: the monthly {label} cap ({cap} credits) is reached. "
            f"Raise caps.{result.source}.credits in config/settings.yaml to continue."
        )
    elif result.exhausted:
        lines.append("That was the last page for this ICP.")
    else:
        lines.append(f"Next run continues at page {result.next_page}.")
    return "\n".join(lines)
