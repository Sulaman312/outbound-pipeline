"""The Clay round trip: a CSV of companies goes to Clay, and Clay's CSV of people comes back.

Export picks new companies and writes data/clay/batch_<time>_<segment>.csv with our own
company_id. It marks those companies "exported" so they're never sent twice, and records the
batch.

Import reads the CSV you downloaded from Clay and matches each row to our company: by
company_id, then by domain, then by the email's domain. It applies rules.py and saves each
person as a contact. Clay's column names don't have to be exact; detect_columns() finds them,
and the web page lets you pick any it can't.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from outbound import db, rules
from outbound.normalize import normalize_domain, normalize_email

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
    conn: sqlite3.Connection, root: Path, segment: str | None, rows: int = DEFAULT_ROWS
) -> ExportResult | None:
    """Write the next `rows` waiting companies to a CSV for Clay. None if nothing is waiting."""
    companies = db.companies_for_clay(conn, segment, rows)
    if not companies:
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = root / "data" / "clay" / f"batch_{stamp}_{segment or 'all'}.csv"
    with conn:  # if the file can't be written, nothing is marked as exported
        batch_id = db.create_batch(conn, path.relative_to(root).as_posix(), len(companies), segment)
        db.mark_exported(conn, [company["id"] for company in companies], batch_id)
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
    decisions: Counter[str] = field(default_factory=Counter)
    batches: list[int] = field(default_factory=list)


def _cell(row: dict[str, str], mapping: dict[str, str | None], name: str) -> str:
    header = mapping.get(name)
    return (row.get(header) or "").strip() if header else ""


def _match_company(
    conn: sqlite3.Connection, row: dict[str, str], mapping: dict[str, str | None], email: str | None
) -> sqlite3.Row | None:
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
    conn: sqlite3.Connection,
    rows: list[dict[str, str]],
    mapping: dict[str, str | None],
    *,
    account: str | None = None,
    credits: float | None = None,
) -> ImportResult:
    """Save Clay's people as contacts. All or nothing: a failure saves none of the file."""
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
            status = rules.clay_status(_cell(row, mapping, "email_status"), bool(email))
            suppressed = bool(email) and (
                db.is_suppressed(conn, email) or db.is_suppressed(conn, email.split("@", 1)[1])
            )
            decision, reason = rules.decide(email, status, suppressed)
            saved = db.insert_contact(
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
                    "decision": decision,
                    "reason": reason,
                    "raw": json.dumps(row, ensure_ascii=False),
                },
            )
            if saved:
                result.saved += 1
                result.decisions[decision] += 1
            else:
                result.duplicate += 1
            db.set_company_status(conn, company["id"], "enriched" if email else "no_contact")
            if company["batch_id"] is not None:
                touched.add(company["batch_id"])
        one_batch = len(touched) == 1
        for batch_id in touched:
            db.finish_batch(
                conn, batch_id, account if one_batch else None, credits if one_batch else None
            )
    result.batches = sorted(touched)
    return result


# --- reports ------------------------------------------------------------------------------------


def describe_import(conn: sqlite3.Connection, result: ImportResult, credits: float | None) -> str:
    d = result.decisions
    lines = [
        f"read {result.rows} rows from Clay",
        f"  matched to our companies   {result.matched}",
        f"  not matched                {result.unmatched}",
        f"  saved as contacts          {result.saved}",
        f"  already had that email     {result.duplicate}",
        "decisions for the new contacts:",
        f"  ready   {d['ready']:>4}   Clay says valid",
        f"  maybe   {d['maybe']:>4}   catch-all or unknown: re-checked with Instantly at the next step",
        f"  hold    {d['hold']:>4}   role addresses like info@ (waiting on decision D5)",
        f"  drop    {d['drop']:>4}   no email, invalid, or do-not-contact",
    ]
    batches = {row["id"]: row for row in db.list_batches(conn)}
    for batch_id in result.batches:
        b = batches[batch_id]
        lines.append(
            f"batch {batch_id}: {b['rows']} companies sent, {b['people']} people back, "
            f"{b['emails']} with an email, {b['ready'] or 0} ready"
        )
    if credits is not None and len(result.batches) > 1:
        lines.append(
            "note: this file covers several batches, so the credits weren't saved on any of them"
        )
    elif credits and d["ready"]:
        lines.append(f"cost: {credits:g} Clay credits, {credits / d['ready']:.2f} per ready email")
    return "\n".join(lines)
