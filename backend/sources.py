"""The one list of places companies come from, and the settings each ICP keeps for each of them.

An ICP says who we target. It keeps one block of settings per source (see `icp_sources` in
db.py), so adding a source means adding it here and writing its run function, never changing
ICPs. Every source saves into the same companies table and feeds the same Clay flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str  # "list" (one per line), "ranges" (like 1,10), "int", "text", "bool"
    help: str
    required: bool = False
    default: Any = None  # used when the field is left empty
    low: int | None = None  # "int": smallest allowed
    high: int | None = None  # "int": largest allowed
    pattern: str | None = None  # "text": the value must match this (whole value)
    pattern_help: str = ""  # "text": what a good value looks like


@dataclass(frozen=True)
class Source:
    key: str  # used in ICP settings and on the screens, like "google_maps"
    label: str
    provider: str  # companies.source, and the usage/caps name, like "google_places"
    built: bool
    cost: str  # in plain words, for the screens
    key_env: str  # the .env name of its API key
    cap_unit: str  # what config/settings.yaml caps for it, like caps.apollo.credits
    fields: tuple[Field, ...]


SOURCES: tuple[Source, ...] = (
    Source(
        "apollo",
        "Apollo",
        "apollo",
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
        "google_places",
        True,
        "1 Google request per page of up to 20 places (free up to 1,000 a month)",
        "GOOGLE_PLACES_API_KEY",
        "requests",
        (
            Field(
                "queries",
                "Search phrases",
                "list",
                'What you would type in Maps, like "vet clinic". Each one is searched in each city.',
                required=True,
            ),
            Field("cities", "Cities", "list", 'Like "Austin, TX"', required=True),
            Field(
                "region_code",
                "Region code",
                "text",
                'Two letters, like "us"',
                default="us",
                pattern=r"[a-z]{2}",
                pattern_help='two letters, like "us"',
            ),
            Field(
                "place_type",
                "Google place type (optional)",
                "text",
                'Only this type of place, like "veterinary_care". Leave empty for any.',
                pattern=r"[a-z][a-z_]*",
                pattern_help='lowercase words joined by _, like "veterinary_care"',
            ),
            Field(
                "pages_per_query",
                "Pages per search",
                "int",
                "1 to 3 pages of 20 places. Google stops at 60 places per search.",
                default=1,
                low=1,
                high=3,
            ),
            Field(
                "skip_chains",
                "Skip chains",
                "bool",
                "A website seen at 3 or more places is a likely chain: don't save it, and keep "
                "it out of Clay",
                default=True,
            ),
        ),
    ),
)

BY_KEY: dict[str, Source] = {source.key: source for source in SOURCES}
