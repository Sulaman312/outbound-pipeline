"""The Clay round trip: a CSV of companies goes to Clay, and Clay's CSV of people comes back.

Export claims new companies in one UPDATE ... RETURNING so two laptops never take the same
row, writes data/clay/batch_<time>_<segment>.csv with our own company_id, and records the batch.

Import reads the CSV you downloaded from Clay and matches each row to our company: by
company_id, then by domain, then by the email's domain. It applies verify.decide() and saves
each person as a lead. Clay's column names don't have to be exact; detect_columns() finds them.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend import db
from backend.db import Connection
from backend.normalize import normalize_domain, normalize_email
from backend.stages import verify

DEFAULT_ROWS = 200  # Clay Free allows 200 rows per table; use 50 on a Clay trial
EXPORT_COLUMNS = ("company_id", "domain", "name", "linkedin_url", "segment")

# Our field -> (label shown to people, Clay column names it may have, best first).
FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "company_id": ("Our company_id", ("company_id", "companyid")),
    "domain": ("Company domain", ("company_domain", "domain", "company_website", "website")),
    "email": (
        "Email",
        ("work_email", "email", "find_work_email", "email_address", "business_email"),
    ),
    "email_status": (
        "Email check result",
        (
            "email_status",
            "validate_email",
            "email_validation",
            "validation_status",
            "verification_status",
            "email_verification",
        ),
    ),
    "first_name": ("First name", ("first_name", "firstname")),
    "last_name": ("Last name", ("last_name", "lastname")),
    "title": ("Job title", ("job_title", "title", "position")),
    "linkedin_url": (
        "Person's LinkedIn",
        ("linkedin_profile", "person_linkedin_url", "linkedin_profile_url", "linkedin_url"),
    ),
}


# --- export -------------------------------------------------------------------------------------


@dataclass
class ExportResult:
    batch_id: int
    path: Path
    rows: int


def export_batch(
    conn: Connection, root: Path, segment: str | None, rows: int = DEFAULT_ROWS
) -> ExportResult | None:
    """Claim and write the next `rows` waiting companies to a CSV for Clay. None if nothing waiting."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    rel = f"data/clay/batch_{stamp}_{segment or 'all'}.csv"
    path = root / rel
    with conn:  # if the file can't be written, nothing stays claimed
        batch_id = db.create_batch(conn, rel, 0, segment)
        companies = db.claim_companies_for_clay(conn, segment, rows, batch_id)
        if not companies:
            db.delete_batch(conn, batch_id)
            return None
        db.update_batch(conn, batch_id, file=rel, rows=len(companies))
        path.parent.mkdir(parents=True, exist_ok=True)
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(EXPORT_COLUMNS)
        for company in companies:
            writer.writerow(
                [
                    company["id"],
                    company["domain"],
                    company["name"],
                    company["linkedin_url"] or "",
                    company["segment"],
                ]
            )
        path.write_text(
            buffer.getvalue(), encoding="utf-8", newline=""
        )  # no BOM: Clay reads it as-is
    return ExportResult(batch_id=batch_id, path=path, rows=len(companies))


# --- import -------------------------------------------------------------------------------------


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")


def detect_columns(headers: list[str]) -> dict[str, str | None]:
    """For each of our fields, the Clay column that holds it (None if not found)."""
    by_key = {_key(header): header for header in headers}
    mapping: dict[str, str | None] = {}
    used: set[str] = set()
    for name, (_, aliases) in FIELDS.items():
        mapping[name] = None
        for alias in aliases:
            header = by_key.get(alias)
            if header and header not in used:
                mapping[name] = header
                used.add(header)
                break
    return mapping


def missing_fields(mapping: dict[str, str | None]) -> list[str]:
    """What's still needed before an import can run."""
    missing = []
    if not mapping.get("email"):
        missing.append("Email")
    if not mapping.get("company_id") and not mapping.get("domain"):
        missing.append("Our company_id or Company domain")
    return missing


def check_mapping(headers: list[str], mapping: dict[str, str | None]) -> dict[str, str | None]:
    """A mapping someone picked by hand, checked against the file. Raises ValueError if wrong.

    Every one of our fields is in the result; a field left out or set to "" means "not in the file".
    """
    unknown = sorted(set(mapping) - set(FIELDS))
    if unknown:
        raise ValueError(f"unknown field {unknown[0]!r}")
    checked: dict[str, str | None] = {}
    for name in FIELDS:
        header = mapping.get(name) or None
        if header is not None and header not in headers:
            raise ValueError(f"the file has no column called {header!r}")
        checked[name] = header
    missing = missing_fields(checked)
    if missing:
        raise ValueError(f"choose a column for: {', '.join(missing)}")
    return checked


def read_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """(headers, rows) from CSV text."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    return list(reader.fieldnames or []), list(reader)


@dataclass
class ImportResult:
    rows: int = 0
    matched: int = 0
    unmatched: int = 0
    saved: int = 0
    duplicate: int = 0
    states: Counter[str] = field(default_factory=Counter)
    batches: list[int] = field(default_factory=list)


def _cell(row: dict[str, str], mapping: dict[str, str | None], name: str) -> str:
    header = mapping.get(name)
    return (row.get(header) or "").strip() if header else ""


def _match_company(
    conn: Connection, row: dict[str, str], mapping: dict[str, str | None], email: str | None
) -> Any:
    company_id = _cell(row, mapping, "company_id")
    if company_id.isdigit():
        company = db.get_company(conn, int(company_id))
        if company is not None:
            return company
    for candidate in (_cell(row, mapping, "domain"), email.split("@", 1)[1] if email else ""):
        domain = normalize_domain(candidate)
        if domain:
            company = db.find_company_by_domain(conn, domain)
            if company is not None:
                return company
    return None


def import_rows(
    conn: Connection,
    rows: list[dict[str, str]],
    mapping: dict[str, str | None],
    *,
    account: str | None = None,
    credits: float | None = None,
) -> ImportResult:
    """Save Clay's people as leads. All or nothing: a failure saves none of the file."""
    missing = missing_fields(mapping)
    if missing:
        raise ValueError(f"can't tell which Clay column is: {', '.join(missing)}")
    result = ImportResult()
    touched: set[int] = set()
    with conn:
        for row in rows:
            result.rows += 1
            email = normalize_email(_cell(row, mapping, "email"))
            company = _match_company(conn, row, mapping, email)
            if company is None:
                result.unmatched += 1
                continue
            result.matched += 1
            status = verify.clay_status(_cell(row, mapping, "email_status"), bool(email))
            suppressed = bool(email) and (
                db.is_suppressed(conn, email) or db.is_suppressed(conn, email.split("@", 1)[1])
            )
            state, state_reason = verify.decide(email, status, suppressed)
            saved = db.insert_lead(
                conn,
                {
                    "company_id": company["id"],
                    "batch_id": company["batch_id"],
                    "first_name": _cell(row, mapping, "first_name") or None,
                    "last_name": _cell(row, mapping, "last_name") or None,
                    "title": _cell(row, mapping, "title") or None,
                    "email": email,
                    "linkedin_url": _cell(row, mapping, "linkedin_url") or None,
                    "clay_status": status,
                    "state": state,
                    "state_reason": state_reason,
                    "raw": json.dumps(row, ensure_ascii=False),
                },
            )
            if saved:
                result.saved += 1
                result.states[state] += 1
            else:
                result.duplicate += 1
            db.set_company_status(conn, company["id"], "enriched" if email else "no_contact")
            if company["batch_id"] is not None:
                touched.add(int(company["batch_id"]))
        one_batch = len(touched) == 1
        for batch_id in touched:
            db.finish_batch(
                conn, batch_id, account if one_batch else None, credits if one_batch else None
            )
    result.batches = sorted(touched)
    return result


# --- reports ------------------------------------------------------------------------------------


def describe_import(conn: Connection, result: ImportResult, credits: float | None) -> str:
    d = result.states
    lines = [
        f"read {result.rows} rows from Clay",
        f"  matched to our companies   {result.matched}",
        f"  not matched                {result.unmatched}",
        f"  saved as leads             {result.saved}",
        f"  already had that email     {result.duplicate}",
        "states for the new leads:",
        f"  verified     {d['verified']:>4}   Clay says valid",
        f"  needs_check  {d['needs_check']:>4}   catch-all or unknown: re-checked with Instantly next",
        f"  hold         {d['hold']:>4}   role addresses like info@ (waiting on decision D5)",
        f"  dropped      {d['dropped']:>4}   no email, invalid, or do-not-contact",
    ]
    batches = {row["id"]: row for row in db.list_batches(conn)}
    for batch_id in result.batches:
        b = batches[batch_id]
        lines.append(
            f"batch {batch_id}: {b['rows']} companies sent, {b['people']} people back, "
            f"{b['emails']} with an email, {b['verified'] or 0} verified"
        )
    if credits is not None and len(result.batches) > 1:
        lines.append(
            "note: this file covers several batches, so the credits weren't saved on any of them"
        )
    elif credits and d["verified"]:
        lines.append(
            f"cost: {credits:g} Clay credits, {credits / d['verified']:.2f} per verified email"
        )
    return "\n".join(lines)
