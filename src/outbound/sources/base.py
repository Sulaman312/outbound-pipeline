"""What every lead source must implement.

A source turns (ICP options, country) into `SourcedRecord`s. It knows its own
provider's API and nothing about storage, dedupe or other sources. To add a
source (Apify jobs, Crunchbase, a CSV drop...), write one class like
`ApolloSource`, give it an `Options` model, and register it in
`sources/__init__.py`. Nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from outbound.config import Country, Icp
from outbound.http import ApiClient
from outbound.models import SourcedRecord


class SourceOptions(BaseModel):
    """Base for each source's per-ICP options. Unknown keys are an error, so typos surface."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = True


@dataclass(frozen=True)
class PlannedRequest:
    """What a dry run prints: one request the source would make."""

    description: str
    body: dict[str, Any]
    max_requests: int = 1  # upper bound incl. pagination
    billable: bool = False  # counts against a paid/free-tier quota


class LeadSource(ABC):
    name: ClassVar[str]
    Options: ClassVar[type[SourceOptions]]

    def __init__(self, client: ApiClient):
        self.client = client

    def parse_options(self, icp: Icp) -> SourceOptions | None:
        raw = icp.sources.get(self.name)
        if raw is None:
            return None
        opts = self.Options(**raw)
        return opts if opts.enabled else None

    @abstractmethod
    def plan(self, opts: SourceOptions, icp: Icp, country: Country) -> list[PlannedRequest]:
        """The requests `fetch` would make, without making any."""

    @abstractmethod
    def fetch(self, opts: SourceOptions, icp: Icp, country: Country) -> Iterator[SourcedRecord]:
        """Call the provider and yield mapped records."""
