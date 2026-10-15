"""The data contract between stages.

Every stage reads `Lead` objects at one `Stage` and hands them on at the next.
A stage only fills in its own fields; it never rewrites what an earlier stage
produced. Fields for later stages exist here from the start (as optional) so
the shape of a lead never changes underneath anyone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class Stage(str, Enum):
    """Where a lead is in the pipeline. Order matters: each stage moves a lead forward one step."""

    SOURCED = "sourced"  # company (+ maybe a person) found, no email yet
    ENRICHED = "enriched"  # email search done (found or not)
    VERIFIED = "verified"  # email checked, safe to send
    QUEUED = "queued"  # pushed into a sending campaign
    DROPPED = "dropped"  # out for good; see Lead.drop_reason


class EmailStatus(str, Enum):
    UNKNOWN = "unknown"
    VALID = "valid"
    CATCH_ALL = "catch_all"
    RISKY = "risky"
    INVALID = "invalid"


class Company(BaseModel):
    name: str
    domain: str | None = None  # normalised, e.g. "acme.com"
    website: str | None = None
    phone: str | None = None
    country: str  # ISO 3166 alpha-2, e.g. "US"
    city: str | None = None
    address: str | None = None
    industry: str | None = None
    employees: int | None = None  # exact count when a source gives one
    employee_range: str | None = None  # e.g. "1,10" when only a band is known
    legal_name: str | None = None  # used by the UK "limited companies only" rule


class Contact(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    linkedin_url: str | None = None
    source_person_id: str | None = None


class SourcedRecord(BaseModel):
    """One raw hit from one lead source, already mapped to our shape.

    Sources return these; the sourcing stage merges them into Leads.
    """

    source: str  # adapter name, e.g. "apollo"
    source_id: str  # the provider's own id for this record
    company: Company
    contact: Contact | None = None
    signals: list[str] = Field(default_factory=list)  # e.g. "hiring:react"
    raw: dict[str, Any] = Field(default_factory=dict)


class Lead(BaseModel):
    """One company we may email, for one ICP. The unit every stage works on."""

    id: int | None = None
    key: str  # dedupe key, unique per ICP
    icp: str
    country: str
    company: Company
    contact: Contact | None = None
    sources: list[str] = Field(default_factory=list)
    source_ids: dict[str, list[str]] = Field(default_factory=dict)
    signals: list[str] = Field(default_factory=list)

    stage: Stage = Stage.SOURCED
    drop_reason: str | None = None

    # Filled by enrichment.
    email: str | None = None
    email_source_url: str | None = None  # proof of publication (Australia)
    email_provider: str | None = None

    # Filled by verification.
    email_status: EmailStatus = EmailStatus.UNKNOWN

    # Filled by routing / sending.
    campaign: str | None = None  # e.g. "A_UK_Signal_v1"
    personalization: dict[str, str] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
