"""Flat CSV export of leads, for manual steps (e.g. a Clay import) and review."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from outbound.models import Lead

COLUMNS = [
    "lead_id",
    "icp",
    "country",
    "stage",
    "company_name",
    "domain",
    "website",
    "phone",
    "city",
    "address",
    "industry",
    "employees",
    "first_name",
    "last_name",
    "title",
    "linkedin_url",
    "sources",
    "signals",
    "email",
    "email_status",
    "email_source_url",
]


def lead_row(lead: Lead) -> dict[str, object]:
    c, p = lead.company, lead.contact
    return {
        "lead_id": lead.id,
        "icp": lead.icp,
        "country": lead.country,
        "stage": lead.stage.value,
        "company_name": c.name,
        "domain": c.domain,
        "website": c.website,
        "phone": c.phone,
        "city": c.city,
        "address": c.address,
        "industry": c.industry,
        "employees": c.employees,
        "first_name": p.first_name if p else None,
        "last_name": p.last_name if p else None,
        "title": p.title if p else None,
        "linkedin_url": p.linkedin_url if p else None,
        "sources": "|".join(lead.sources),
        "signals": "|".join(lead.signals),
        "email": lead.email,
        "email_status": lead.email_status.value,
        "email_source_url": lead.email_source_url,
    }


def write_csv(leads: Iterable[Lead], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead_row(lead))
            n += 1
    return n
