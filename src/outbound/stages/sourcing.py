"""Stage 1: lead sourcing.

For one ICP and one country: ask each enabled source, drop disqualified and
suppressed companies, and merge everything into the store so one company is
one lead no matter how many sources found it (same domain = same company).

Output contract: leads at Stage.SOURCED with `company` filled, `contact` filled
when a source had a person (Apollo), and `sources` listing who found it.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from outbound.config import Config, Country, Icp
from outbound.errors import BudgetExceededError, ProviderError
from outbound.models import Lead, SourcedRecord
from outbound.normalize import dedupe_key, normalize_name
from outbound.sources import LeadSource, PlannedRequest
from outbound.store import Store

log = logging.getLogger(__name__)


@dataclass
class SourcingResult:
    icp: str
    country: str
    plans: dict[str, list[PlannedRequest]] = field(default_factory=dict)
    counts: Counter = field(default_factory=Counter)
    errors: dict[str, str] = field(default_factory=dict)


class SourcingStage:
    def __init__(self, config: Config, store: Store, sources: list[LeadSource]):
        self.config = config
        self.store = store
        self.sources = sources

    def plan(self, icp_id: str, country_code: str) -> SourcingResult:
        icp, country = self.config.icp(icp_id), self.config.country(country_code)
        result = SourcingResult(icp.id, country.code)
        for source in self.sources:
            opts = source.parse_options(icp)
            if opts:
                result.plans[source.name] = source.plan(opts, icp, country)
        return result

    def run(self, icp_id: str, country_code: str) -> SourcingResult:
        icp, country = self.config.icp(icp_id), self.config.country(country_code)
        if country.code not in icp.countries:
            log.warning("ICP %s does not list %s; running anyway", icp.id, country.code)
        result = SourcingResult(icp.id, country.code)
        run_id = self.store.start_run("sourcing", {"icp": icp.id, "country": country.code})

        for source in self.sources:
            opts = source.parse_options(icp)
            if not opts:
                continue
            # A provider failure (cap reached, bad key) stops that source only, and
            # everything it returned before failing is still committed: those
            # requests were already paid for.
            with self.store.transaction():
                try:
                    for record in source.fetch(opts, icp, country):
                        self.store.save_raw(run_id, record)
                        result.counts[f"{source.name}_fetched"] += 1
                        result.counts[self._ingest(record, icp, country)] += 1
                except (BudgetExceededError, ProviderError) as e:
                    log.error("%s stopped: %s", source.name, e)
                    result.errors[source.name] = str(e)

        self.store.finish_run(run_id, {"counts": dict(result.counts), "errors": result.errors})
        return result

    # -- per record ------------------------------------------------------------

    def _ingest(self, record: SourcedRecord, icp: Icp, country: Country) -> str:
        """Store one record. Returns the outcome name used in the run counts."""
        reason = self._disqualify(record, icp)
        if reason:
            log.debug("disqualified %s: %s", record.company.name, reason)
            return "disqualified"
        if record.company.domain and self.store.is_suppressed(domain=record.company.domain):
            return "suppressed"

        key = dedupe_key(record.company.domain, record.company.name, country.code)
        existing = self.store.get_lead(icp.id, key)
        if existing:
            self.store.save_lead(_merge(existing, record))
            return "merged"

        self.store.save_lead(
            Lead(
                key=key,
                icp=icp.id,
                country=country.code,
                company=record.company,
                contact=record.contact,
                sources=[record.source],
                source_ids={record.source: [record.source_id]},
                signals=record.signals,
            )
        )
        return "new"

    @staticmethod
    def _disqualify(record: SourcedRecord, icp: Icp) -> str | None:
        rules, company = icp.disqualify, record.company
        if company.employees is not None:
            if rules.max_employees is not None and company.employees > rules.max_employees:
                return f"{company.employees} employees > {rules.max_employees}"
            if rules.min_employees is not None and company.employees < rules.min_employees:
                return f"{company.employees} employees < {rules.min_employees}"
        name = normalize_name(company.name)
        for word in rules.name_keywords:
            if normalize_name(word) and normalize_name(word) in name:
                return f"name contains '{word}'"
        if company.domain and company.domain in {d.lower() for d in rules.domains}:
            return "excluded domain"
        return None


def _merge(lead: Lead, record: SourcedRecord) -> Lead:
    """Add a second source's view of the same company without losing anything."""
    if record.source not in lead.sources:
        lead.sources.append(record.source)
    ids = lead.source_ids.setdefault(record.source, [])
    if record.source_id not in ids:
        ids.append(record.source_id)

    # Fill gaps only; the first value seen wins.
    for field_name, value in record.company.model_dump().items():
        if value is not None and getattr(lead.company, field_name) is None:
            setattr(lead.company, field_name, value)
    if lead.contact is None and record.contact is not None:
        lead.contact = record.contact
    for signal in record.signals:
        if signal not in lead.signals:
            lead.signals.append(signal)
    return lead
