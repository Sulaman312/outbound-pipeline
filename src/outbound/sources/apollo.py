"""Apollo People API Search: people + company, 0 credits, no emails.

Docs: https://docs.apollo.io/reference/people-api-search
  POST /api/v1/mixed_people/api_search, up to 100 per page, 500 pages.

The docs publish no response schema, and a third-party integration reports
that this free endpoint obfuscates last names. So the mapping below reads
every field defensively and the full raw payload is stored; the first live run
tells us which fields actually arrive, and only `_map_person` would change.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from pydantic import Field

from outbound.config import Country, Icp
from outbound.models import Company, Contact, SourcedRecord
from outbound.normalize import normalize_domain
from outbound.sources.base import LeadSource, PlannedRequest, SourceOptions

SEARCH_PATH = "/api/v1/mixed_people/api_search"


class ApolloOptions(SourceOptions):
    person_titles: list[str] = Field(default_factory=list)
    include_similar_titles: bool = True
    person_seniorities: list[str] = Field(default_factory=list)
    organization_num_employees_ranges: list[str] = Field(default_factory=list)  # ["1,10"]
    organization_industries: list[str] = Field(default_factory=list)  # lowercase Apollo names
    q_keywords: str | None = None
    q_organization_job_titles: list[str] = Field(default_factory=list)  # hiring signal
    per_page: int = Field(default=100, ge=1, le=100)
    max_pages: int = Field(default=1, ge=1, le=500)
    # Any other documented filter, passed through unchanged.
    extra_filters: dict[str, Any] = Field(default_factory=dict)


class ApolloSource(LeadSource):
    name = "apollo"
    Options = ApolloOptions

    def _body(self, opts: ApolloOptions, country: Country, page: int) -> dict[str, Any]:
        body: dict[str, Any] = {
            "organization_locations": [country.apollo_location],
            "page": page,
            "per_page": opts.per_page,
        }
        optional = {
            "person_titles": opts.person_titles,
            "person_seniorities": opts.person_seniorities,
            "organization_num_employees_ranges": opts.organization_num_employees_ranges,
            "organization_industries": opts.organization_industries,
            "q_keywords": opts.q_keywords,
            "q_organization_job_titles": opts.q_organization_job_titles,
        }
        body.update({k: v for k, v in optional.items() if v})
        if opts.person_titles and not opts.include_similar_titles:
            body["include_similar_titles"] = False
        body.update(opts.extra_filters)
        return body

    def plan(self, opts: ApolloOptions, icp: Icp, country: Country) -> list[PlannedRequest]:
        return [
            PlannedRequest(
                description=f"Apollo people search, ICP {icp.id}, {country.name}, "
                f"up to {opts.max_pages} page(s) x {opts.per_page} (0 credits)",
                body=self._body(opts, country, page=1),
                max_requests=opts.max_pages,
                billable=False,
            )
        ]

    def fetch(self, opts: ApolloOptions, icp: Icp, country: Country) -> Iterator[SourcedRecord]:
        signals = [f"hiring:{t.lower()}" for t in opts.q_organization_job_titles]
        for page in range(1, opts.max_pages + 1):
            data = self.client.post(SEARCH_PATH, json=self._body(opts, country, page))
            people = data.get("people") or []
            for person in people:
                record = self._map_person(person, country, signals)
                if record:
                    yield record
            total_pages = (data.get("pagination") or {}).get("total_pages")
            if not people or (total_pages is not None and page >= total_pages):
                break

    def _map_person(
        self, p: dict[str, Any], country: Country, signals: list[str]
    ) -> SourcedRecord | None:
        org = p.get("organization") or {}
        company_name = org.get("name") or p.get("organization_name")
        if not company_name or not p.get("id"):
            return None
        website = org.get("website_url")
        domain = normalize_domain(org.get("primary_domain") or website)
        phone = org.get("phone") or (org.get("primary_phone") or {}).get("sanitized_number")
        return SourcedRecord(
            source=self.name,
            source_id=str(p["id"]),
            company=Company(
                name=company_name,
                domain=domain,
                website=website,
                phone=phone,
                country=country.code,
                city=org.get("city") or p.get("city"),
                industry=org.get("industry"),
                employees=org.get("estimated_num_employees"),
            ),
            contact=Contact(
                first_name=p.get("first_name"),
                last_name=p.get("last_name"),  # None if Apollo only sends the obfuscated form
                title=p.get("title"),
                linkedin_url=p.get("linkedin_url"),
                source_person_id=str(p["id"]),
            ),
            signals=list(signals),
            raw=p,
        )
