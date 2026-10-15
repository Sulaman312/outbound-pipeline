"""steps/clay.py: the file that goes to Clay, and reading Clay's file back."""

from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path

import pytest

from outbound import db
from outbound.steps import clay

CLAY_HEADERS = [
    "Company Domain",
    "First Name",
    "Last Name",
    "Job Title",
    "Work Email",
    "Validate Email",
    "LinkedIn Profile",
]


@pytest.fixture
def conn(project: Path) -> sqlite3.Connection:
    connection = db.connect(project / "data" / "outbound.db")
    with connection:
        for i in range(1, 6):
            db.insert_company(
                connection,
                {
                    "domain": f"firm{i}.com",
                    "name": f"Firm {i}",
                    "source": "apollo",
                    "source_id": f"org{i}",
                    "segment": "ai_accounting" if i <= 3 else "frontend_agencies",
                    "linkedin_url": f"http://www.linkedin.com/company/firm{i}",
                },
            )
    yield connection
    connection.close()


def clay_csv(rows: list[dict[str, str]], headers: list[str] = CLAY_HEADERS) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def person(domain: str, email: str, status: str = "valid", first: str = "Jane") -> dict[str, str]:
    return {
        "Company Domain": domain,
        "First Name": first,
        "Last Name": "Doe",
        "Job Title": "Founder",
        "Work Email": email,
        "Validate Email": status,
        "LinkedIn Profile": "https://www.linkedin.com/in/janedoe",
    }


def statuses(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["domain"]: row["status"] for row in db.list_companies(conn)}


# --- export ---------------------------------------------------------------------------------------


def test_export_writes_file_and_marks_companies(conn: sqlite3.Connection, project: Path) -> None:
    with conn:
        db.add_suppression(conn, "firm2.com", "domain", "client")
    result = clay.export_batch(conn, project, "ai_accounting", rows=10)
    assert result is not None and result.rows == 2  # firm1 and firm3; firm2 is do-not-contact
    text = result.path.read_text(encoding="utf-8")
    assert not text.startswith("﻿")  # no BOM, so Clay's first column name stays clean
    rows = list(csv.DictReader(io.StringIO(text)))
    assert [r["domain"] for r in rows] == ["firm1.com", "firm3.com"]
    assert rows[0]["company_id"].isdigit()
    assert statuses(conn)["firm1.com"] == "exported"
    assert statuses(conn)["firm4.com"] == "new"


def test_export_respects_row_limit_and_never_repeats(
    conn: sqlite3.Connection, project: Path
) -> None:
    first = clay.export_batch(conn, project, None, rows=3)
    second = clay.export_batch(conn, project, None, rows=3)
    assert (first.rows, second.rows) == (3, 2)
    assert clay.export_batch(conn, project, None, rows=3) is None
    assert first.batch_id != second.batch_id


# --- columns ------------------------------------------------------------------------------------


def test_detect_clay_style_headers() -> None:
    mapping = clay.detect_columns(CLAY_HEADERS)
    assert mapping["domain"] == "Company Domain"
    assert mapping["email"] == "Work Email"
    assert mapping["email_status"] == "Validate Email"
    assert mapping["first_name"] == "First Name"
    assert mapping["title"] == "Job Title"
    assert mapping["linkedin_url"] == "LinkedIn Profile"
    assert mapping["company_id"] is None
    assert clay.missing_fields(mapping) == []


def test_missing_fields_are_named() -> None:
    mapping = clay.detect_columns(["Full Name", "Notes"])
    assert clay.missing_fields(mapping) == ["Email", "Our company_id or Company domain"]


def test_read_csv_ignores_a_bom() -> None:
    headers, rows = clay.read_csv("﻿Work Email,Company Domain\r\na@b.com,b.com\r\n")
    assert headers == ["Work Email", "Company Domain"]
    assert rows == [{"Work Email": "a@b.com", "Company Domain": "b.com"}]


# --- import -------------------------------------------------------------------------------------


def run_import(conn: sqlite3.Connection, text: str, **kwargs: object) -> clay.ImportResult:
    headers, rows = clay.read_csv(text)
    return clay.import_rows(conn, rows, clay.detect_columns(headers), **kwargs)


def test_import_decides_and_saves(conn: sqlite3.Connection, project: Path) -> None:
    clay.export_batch(conn, project, None, rows=10)
    with conn:
        db.add_suppression(conn, "blocked@firm5.com", "email", "asked to stop")
    text = clay_csv(
        [
            person("firm1.com", "Jane@Firm1.com", "valid"),
            person("firm2.com", "joe@firm2.com", "catch-all", first="Joe"),
            person("firm3.com", "info@firm3.com", "valid"),
            person("firm4.com", "", ""),
            person("firm5.com", "blocked@firm5.com", "valid"),
            person("nobody.com", "x@nobody.com", "valid"),
        ]
    )
    result = run_import(conn, text, account="clay-1", credits=12)

    assert (result.rows, result.matched, result.unmatched, result.saved) == (6, 5, 1, 5)
    assert dict(result.decisions) == {"ready": 1, "maybe": 1, "hold": 1, "drop": 2}
    contacts = {row["company_domain"]: row for row in db.list_contacts(conn)}
    assert contacts["firm1.com"]["email"] == "jane@firm1.com"
    assert contacts["firm1.com"]["title"] == "Founder"
    assert contacts["firm2.com"]["clay_status"] == "catch_all"
    assert contacts["firm5.com"]["reason"] == "on the do-not-contact list"
    assert statuses(conn)["firm1.com"] == "enriched"
    assert statuses(conn)["firm4.com"] == "no_contact"

    batch = db.list_batches(conn)[0]
    assert (
        batch["imported_at"] and batch["clay_account"] == "clay-1" and batch["clay_credits"] == 12
    )
    assert (batch["people"], batch["emails"], batch["ready"]) == (5, 4, 1)


def test_companies_clay_returned_nothing_for_become_no_contact(
    conn: sqlite3.Connection, project: Path
) -> None:
    clay.export_batch(conn, project, "ai_accounting", rows=10)
    run_import(conn, clay_csv([person("firm1.com", "jane@firm1.com")]))
    assert statuses(conn) == {
        "firm1.com": "enriched",
        "firm2.com": "no_contact",
        "firm3.com": "no_contact",
        "firm4.com": "new",
        "firm5.com": "new",
    }


def test_import_twice_is_safe(conn: sqlite3.Connection, project: Path) -> None:
    clay.export_batch(conn, project, None, rows=10)
    text = clay_csv([person("firm1.com", "jane@firm1.com")])
    run_import(conn, text)
    again = run_import(conn, text)
    assert (again.saved, again.duplicate) == (0, 1)
    assert len(db.list_contacts(conn)) == 1


def test_match_by_company_id_or_email_domain(conn: sqlite3.Connection, project: Path) -> None:
    exported = clay.export_batch(conn, project, None, rows=10)
    ids = {
        r["domain"]: r["company_id"] for r in csv.DictReader(io.StringIO(exported.path.read_text()))
    }
    text = clay_csv(
        [
            {
                "company_id": ids["firm2.com"],
                "Work Email": "a@elsewhere.com",
                "Validate Email": "valid",
            },
            {"company_id": "", "Work Email": "b@firm3.com", "Validate Email": "valid"},
        ],
        headers=["company_id", "Work Email", "Validate Email"],
    )
    result = run_import(conn, text)
    assert result.matched == 2
    domains = sorted(row["company_domain"] for row in db.list_contacts(conn))
    assert domains == ["firm2.com", "firm3.com"]


def test_import_refuses_without_needed_columns(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="Email"):
        clay.import_rows(conn, [{"Notes": "x"}], clay.detect_columns(["Notes"]))


def test_describe_import(conn: sqlite3.Connection, project: Path) -> None:
    clay.export_batch(conn, project, None, rows=10)
    result = run_import(conn, clay_csv([person("firm1.com", "jane@firm1.com")]), credits=4)
    text = clay.describe_import(conn, result, 4)
    assert "ready      1" in text
    assert "batch 1: 5 companies sent, 1 people back, 1 with an email, 1 ready" in text
    assert "4 Clay credits, 4.00 per ready email" in text
