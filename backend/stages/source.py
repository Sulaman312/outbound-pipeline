"""Find companies for one ICP from one source, and save the new ones.

Every source saves into the same companies table: one row per domain, ever, and never a
do-not-contact domain. So a company belongs to the first ICP (and source) that saves it, and a
later one skips it. Run the narrowest ICP (one with a signal) before its broader twin.

A dry run (the default) only describes the request and what it could cost. It never touches
the network. A live run reserves usage under the monthly cap before each call, one page at a
time, and remembers where it stopped, so the next run continues instead of paying for the same
page twice. A failed call keeps its reservation.

- Apollo: one search per ICP; progress is the next page.
- Google Maps: one search per phrase x city; progress is kept per search (pages done and
  Google's next-page token). Changing the region or place type starts every search again.
  A website seen at 3 or more places is a likely chain.
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
from backend.integrations import apollo, google_places
from backend.normalize import normalize_domain
from backend.sources import BY_KEY

MAX_PAGES_PER_RUN = 50
APOLLO, GOOGLE = "apollo", "google_maps"
PROVIDER, UNIT = "apollo", "credits"  # Apollo's monthly usage counter
CHAIN_PLACES = 3  # a website at this many places or more is a likely chain


@dataclass
class SourceResult:
    source: str = APOLLO
    pages: int = 0
    credits: int = 0  # Apollo credits, or Google requests
    seen: int = 0
    saved: int = 0
    duplicate: int = 0
    no_domain: int = 0
    suppressed: int = 0
    closed: int = 0
    chains: int = 0
    total_entries: int | None = None
    next_page: int = 1
    searches_left: int = 0
    exhausted: bool = False
    stopped_by_cap: bool = False
    error: str | None = None


@dataclass
class Search:
    """One Google Maps search (a phrase in a city) and how far it got."""

    query: str
    pages_done: int
    next_token: str | None
    exhausted: bool
    remaining: int  # pages this run may still fetch


# --- checks shared by the CLI and the app -------------------------------------------------------


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
    return caps.get(source.provider, {}).get(source.cap_unit)


def used_this_month(conn: Connection, source_key: str) -> int:
    source = BY_KEY[source_key]
    return db.usage_this_month(conn, source.provider, source.cap_unit)


def live_problem(source_key: str, api_key: str, cap: int | None) -> str | None:
    """Why a live run can't start, or None. The CLI and the app both ask this first."""
    source = BY_KEY[source_key]
    if not api_key:
        return f"{source.key_env} isn't set. Add it to the .env file in the project folder."
    if cap is None:
        return (
            f"set caps.{source.provider}.{source.cap_unit} in config/settings.yaml before a "
            "live run."
        )
    return None


def credits_for(conn: Connection, icp: Icp, source_key: str, pages: int) -> int:
    """The most a run can spend: Apollo credits for `pages` pages, or Google requests left."""
    if icp_problem(icp, source_key):
        return 0
    if source_key == APOLLO:
        return pages * apollo.CREDITS_PER_PAGE
    return sum(s.remaining for s in google_plan(conn, icp)) * google_places.REQUESTS_PER_PAGE


# --- progress -----------------------------------------------------------------------------------


def filters_hash(source_key: str, settings: dict[str, Any]) -> str:
    """Changes whenever the settings that change a source's results change."""
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
        # Per search, the phrase and city are the search itself; these apply to all of them.
        parts = [settings.get("region_code"), settings.get("place_type")]
    text = json.dumps(parts, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def start_point(conn: Connection, icp: Icp, source_key: str) -> tuple[int, bool, int | None]:
    """Apollo: (next page, no more pages?, last reported total). Changed -> back to page 1."""
    row = db.get_progress(conn, icp.key, source_key)
    if row is None or row["filters_hash"] != filters_hash(source_key, icp.sources[source_key]):
        return 1, False, None
    return int(row["next_page"]), bool(row["exhausted"]), row["total_entries"]


def google_queries(settings: dict[str, Any]) -> list[str]:
    """Every search: each phrase in each city."""
    return [f"{phrase} in {city}" for phrase in settings["queries"] for city in settings["cities"]]


def google_plan(conn: Connection, icp: Icp) -> list[Search]:
    """Every search for this ICP with how far it got. Pages already fetched are never repaid."""
    settings = icp.sources[GOOGLE]
    per_query = min(int(settings["pages_per_query"]), google_places.MAX_PAGES_PER_QUERY)
    fhash = filters_hash(GOOGLE, settings)
    progress = db.get_query_progress(conn, icp.key, GOOGLE)
    plan = []
    for query in google_queries(settings):
        row = progress.get(query)
        if row is not None and row["filters_hash"] == fhash:
            done, token, exhausted = (
                int(row["pages_done"]),
                row["next_token"],
                bool(row["exhausted"]),
            )
        else:
            done, token, exhausted = 0, None, False
        remaining = 0 if exhausted else max(per_query - done, 0)
        plan.append(Search(query, done, token, exhausted, remaining))
    return plan


# --- saving -------------------------------------------------------------------------------------


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


def _save_place(
    conn: Connection, icp: Icp, place: dict[str, Any], skip_chains: bool, result: SourceResult
) -> None:
    """One Google place: skip what can't be used, spot chains, save the rest."""
    company = google_places.to_company(place)
    domain = normalize_domain(company["website"])
    if not domain:
        result.seen += 1
        result.no_domain += 1
        return
    if not google_places.is_operational(place):
        result.seen += 1
        result.closed += 1
        return
    places_here = db.record_place(conn, company["source_id"], domain, icp.key)
    if places_here >= CHAIN_PLACES and not db.is_suppressed(conn, domain):
        db.mark_likely_chain(conn, domain, hold=skip_chains)
        result.chains += 1
        if skip_chains:
            result.seen += 1
            return
    _save(conn, icp, company, google_places.kept_fields(place), result)


# --- Apollo -------------------------------------------------------------------------------------


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
    cost = pages * apollo.CREDITS_PER_PAGE
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


# --- Google Maps --------------------------------------------------------------------------------


def _run_google(
    conn: Connection, icp: Icp, *, client: httpx.Client, api_key: str, cap: int
) -> SourceResult:
    """Each search in turn, up to its pages, 1 reserved request per page."""
    settings = icp.sources[GOOGLE]
    source = BY_KEY[GOOGLE]
    fhash = filters_hash(GOOGLE, settings)
    skip_chains = bool(settings.get("skip_chains", True))
    result = SourceResult(source=GOOGLE)
    plan = google_plan(conn, icp)
    for search in plan:
        token, done = search.next_token, search.pages_done
        for _ in range(search.remaining):
            with conn:
                reserved = db.reserve_usage(conn, source.provider, source.cap_unit, 1, cap)
            if not reserved:
                result.stopped_by_cap = True
                break
            try:
                data = google_places.search_text(
                    client,
                    api_key,
                    search.query,
                    settings["region_code"],
                    settings.get("place_type"),
                    token,
                )
            except google_places.GooglePlacesError as exc:
                result.credits += 1  # the reservation is kept
                result.error = f'"{search.query}": {exc}'
                if token and exc.status == 400:  # Google no longer takes the saved page token
                    with conn:
                        db.save_query_progress(
                            conn, icp.key, GOOGLE, search.query, fhash, done, None, True
                        )
                    result.error += (
                        " The saved next-page token expired; this search is marked done."
                    )
                break
            places = google_places.places_in(data)
            token = google_places.next_page_token(data)
            done += 1
            finished = token is None or done >= google_places.MAX_PAGES_PER_QUERY
            with conn:  # places and progress together; the request is already reserved
                for place in places:
                    _save_place(conn, icp, place, skip_chains, result)
                db.save_query_progress(
                    conn, icp.key, GOOGLE, search.query, fhash, done, token, finished
                )
            result.pages += 1
            result.credits += 1
            if finished:
                break
        if result.error or result.stopped_by_cap:
            break
    result.searches_left = sum(1 for s in google_plan(conn, icp) if s.remaining)
    result.exhausted = result.searches_left == 0
    return result


def _describe_google(conn: Connection, icp: Icp, cap: int | None) -> list[str]:
    settings = icp.sources[GOOGLE]
    plan = google_plan(conn, icp)
    used = used_this_month(conn, GOOGLE)
    cost = sum(s.remaining for s in plan)
    place_type = settings.get("place_type")
    lines = [
        f"request:  POST {google_places.BASE_URL}{google_places.SEARCH_PATH}",
        "fields:   " + ", ".join(google_places.FIELDS) + " (nothing else: no reviews, no photos)",
        f"region:   {settings['region_code']}   language: {google_places.LANGUAGE}   "
        + (f"place type: {place_type} (strict)" if place_type else "place type: any"),
        f"searches: {len(settings['queries'])} phrase(s) x {len(settings['cities'])} city(ies) "
        f"= {len(plan)}, up to {settings['pages_per_query']} page(s) of "
        f"{google_places.PAGE_SIZE} each",
    ]
    for search in plan:
        if search.remaining:
            state = f"{search.remaining} request(s)"
        elif search.exhausted:
            state = "done"
        else:
            state = "done (raise pages per search for more)"
        if search.pages_done and search.remaining:
            state += f", after {search.pages_done} page(s) done"
        lines.append(f"          {search.query}  ->  {state}")
    lines.append(f"cost:     up to {cost} Google request(s), 1 per page (first 1,000 a month free)")
    if cap is None:
        lines.append("budget:   no Google cap in config/settings.yaml, so live runs are blocked")
    else:
        lines.append(f"budget:   {used} of {cap} requests used this month ({db.current_month()})")
        if used + cost > cap:
            lines.append(f"note:     the cap leaves room for only {max(cap - used, 0)} request(s)")
    lines.append(
        "chains:   "
        + ("skipped" if settings.get("skip_chains", True) else "saved and marked")
        + f" (a website at {CHAIN_PLACES} or more places)"
    )
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
    if icp.sources.get(source_key):
        if source_key == APOLLO:
            lines += _describe_apollo(conn, icp, pages, cap, per_page)
        elif source_key == GOOGLE:
            lines += _describe_google(conn, icp, cap)
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
    """Fetch for this ICP from this source and save usable companies. Pages: Apollo only."""
    problem = icp_problem(icp, source_key)
    if problem:
        raise ValueError(problem)
    if source_key == GOOGLE:
        return _run_google(conn, icp, client=client, api_key=api_key, cap=cap)
    return _run_apollo(
        conn, icp, client=client, api_key=api_key, cap=cap, pages=pages, per_page=per_page
    )


def summarize(result: SourceResult, *, used: int, cap: int) -> str:
    """The report printed after a live run."""
    source = BY_KEY[result.source]
    label, unit = source.label, source.cap_unit
    if result.pages == 0 and result.exhausted and not result.error:
        return (
            f"Nothing left to fetch from {label} for this ICP. Change its {label} settings on the "
            "ICPs page to search again."
        )
    lines = [
        f"done: {result.pages} page(s), {result.credits} {unit} ({used} of {cap} used this month)",
        f"  found                {result.seen}",
        f"  saved (new)          {result.saved}",
        f"  already saved        {result.duplicate}   (by this ICP or another one)",
        f"  no website           {result.no_domain}",
    ]
    if result.source == GOOGLE:
        lines.append(f"  closed               {result.closed}")
        lines.append(f"  likely chains        {result.chains}")
    lines.append(f"  do-not-contact       {result.suppressed}")
    if result.total_entries is not None:
        lines.append(f"{label} reports about {result.total_entries:,} matching companies.")
    if result.error:
        lines.append(f"Stopped by an error: {result.error}")
    elif result.stopped_by_cap:
        lines.append(
            f"Stopped: the monthly {label} cap ({cap} {unit}) is reached. "
            f"Raise caps.{source.provider}.{unit} in config/settings.yaml to continue."
        )
    elif result.source == GOOGLE:
        lines.append(
            "Every search is done."
            if result.exhausted
            else f"{result.searches_left} search(es) still have pages to fetch."
        )
    elif result.exhausted:
        lines.append("That was the last page for this ICP.")
    else:
        lines.append(f"Next run continues at page {result.next_page}.")
    return "\n".join(lines)
