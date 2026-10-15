"""Google Places API (New) Text Search: local businesses with website + phone.

Docs: https://developers.google.com/maps/documentation/places/web-service/text-search
  POST /v1/places:searchText, X-Goog-FieldMask required, 20 per page,
  60 max per query across pages. websiteUri and phone numbers are on the
  Enterprise SKU, so every request here is billed at Enterprise rate once the
  free tier is used; settings.yaml caps requests per month.

Places has no employee count, no owner and no email. Those come later
(enrichment). Records here are company-only.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from pydantic import Field

from outbound.config import Country, Icp
from outbound.models import Company, SourcedRecord
from outbound.normalize import normalize_domain
from outbound.sources.base import LeadSource, PlannedRequest, SourceOptions

SEARCH_PATH = "/v1/places:searchText"

FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.businessStatus",
        "places.primaryType",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "nextPageToken",
    ]
)


class GooglePlacesOptions(SourceOptions):
    queries: list[str]  # e.g. "psychiatry clinic"
    cities: dict[str, list[str]] = Field(default_factory=dict)  # country code -> cities
    included_type: str | None = None  # Places type, e.g. "dentist"
    strict_type_filtering: bool = False
    max_pages: int = Field(default=1, ge=1, le=3)
    skip_without_website: bool = True  # no website = no email to find


class GooglePlacesSource(LeadSource):
    name = "google_places"
    Options = GooglePlacesOptions

    def _searches(self, opts: GooglePlacesOptions, country: Country) -> list[str]:
        cities = opts.cities.get(country.code, [])
        if not cities:
            return [f"{q} in {country.name}" for q in opts.queries]
        return [f"{q} in {city}" for q in opts.queries for city in cities]

    def _body(
        self, opts: GooglePlacesOptions, country: Country, text: str, page_token: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "textQuery": text,
            "regionCode": country.places_region_code,
            "pageSize": 20,
        }
        if opts.included_type:
            body["includedType"] = opts.included_type
            body["strictTypeFiltering"] = opts.strict_type_filtering
        if page_token:
            body["pageToken"] = page_token
        return body

    def plan(self, opts: GooglePlacesOptions, icp: Icp, country: Country) -> list[PlannedRequest]:
        return [
            PlannedRequest(
                description=f"Places text search '{text}' (up to {opts.max_pages} page(s), "
                f"Enterprise SKU)",
                body=self._body(opts, country, text),
                max_requests=opts.max_pages,
                billable=True,
            )
            for text in self._searches(opts, country)
        ]

    def fetch(
        self, opts: GooglePlacesOptions, icp: Icp, country: Country
    ) -> Iterator[SourcedRecord]:
        headers = {"X-Goog-FieldMask": FIELD_MASK}
        for text in self._searches(opts, country):
            token: str | None = None
            for _ in range(opts.max_pages):
                data = self.client.post(
                    SEARCH_PATH, json=self._body(opts, country, text, token), headers=headers
                )
                for place in data.get("places") or []:
                    record = self._map_place(place, opts, country)
                    if record:
                        yield record
                token = data.get("nextPageToken")
                if not token:
                    break

    def _map_place(
        self, p: dict[str, Any], opts: GooglePlacesOptions, country: Country
    ) -> SourcedRecord | None:
        if p.get("businessStatus") not in (None, "OPERATIONAL"):
            return None
        name = (p.get("displayName") or {}).get("text")
        website = p.get("websiteUri")
        domain = normalize_domain(website)
        if not name or not p.get("id"):
            return None
        if opts.skip_without_website and not domain:
            return None
        return SourcedRecord(
            source=self.name,
            source_id=p["id"],
            company=Company(
                name=name,
                domain=domain,
                website=website,
                phone=p.get("nationalPhoneNumber"),
                country=country.code,
                address=p.get("formattedAddress"),
                industry=p.get("primaryType"),
            ),
            raw=p,
        )
