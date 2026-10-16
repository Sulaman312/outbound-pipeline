"""The one list of places companies come from, and the settings each ICP keeps for each of them.

An ICP says who we target. It keeps one block of settings per source (see `icp_sources` in
db.py), so adding a source means adding it here and writing its run function, never changing
ICPs. Every source saves into the same companies table and feeds the same Clay flow.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str  # "list" (one per line), "ranges" (like 1,10), "int"
    help: str
    required: bool = False


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    built: bool
    cost: str  # in plain words, for the screens
    key_env: str  # the .env name of its API key
    cap_unit: str  # what config/settings.yaml caps for it, like caps.apollo.credits
    fields: tuple[Field, ...]


SOURCES: tuple[Source, ...] = (
    Source(
        "apollo",
        "Apollo",
        True,
        "1 Apollo credit per page of up to 100 companies",
        "APOLLO_API_KEY",
        "credits",
        (
            Field(
                "hq_locations",
                "Company HQ locations",
                "list",
                "Countries, US states or cities, like United States, Texas or Austin",
                required=True,
            ),
            Field(
                "employee_ranges",
                "Headcount ranges",
                "ranges",
                'Like "1,10" or "11,50"',
                required=True,
            ),
            Field(
                "keywords", "Company keywords", "list", "A company matches if it has any of them"
            ),
            Field(
                "job_titles",
                "Job-post signal: job titles",
                "list",
                "Only companies with an open job post for one of these titles",
            ),
            Field(
                "job_posted_within_days",
                "Job-post signal: posted in the last N days",
                "int",
                "Leave empty for any time",
            ),
        ),
    ),
    Source(
        "google_maps",
        "Google Maps",
        False,
        "not built yet (M1b)",
        "",  # decided in M1b
        "",
        (
            Field(
                "queries",
                "Search phrases",
                "list",
                'What you would type in Maps, like "vet clinic"',
            ),
            Field("cities", "Cities", "list", 'Like "Austin, TX"'),
        ),
    ),
)

BY_KEY: dict[str, Source] = {source.key: source for source in SOURCES}
