"""stages/verify.py: reading Clay's email check, and the verified / needs_check / hold / dropped decision."""

from __future__ import annotations

import pytest

from backend.stages.verify import clay_status, decide, is_role_address


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("valid", "valid"),
        ("Valid", "valid"),
        ("Safe to send", "valid"),
        ("deliverable", "valid"),
        ("invalid", "invalid"),
        ("Undeliverable", "invalid"),
        ("catch-all", "catch_all"),
        ("Catch All", "catch_all"),
        ("accept_all", "catch_all"),
        ("valid (catch-all)", "catch_all"),
        ("risky", "unknown"),
        ("", "unknown"),
        ("something new", "unknown"),
    ],
)
def test_clay_status(text: str, expected: str) -> None:
    assert clay_status(text, has_email=True) == expected


def test_clay_status_without_email() -> None:
    assert clay_status("valid", has_email=False) == "none"


def test_role_addresses() -> None:
    assert is_role_address("info@acme.com")
    assert is_role_address("hello@acme.com")
    assert not is_role_address("jane@acme.com")


@pytest.mark.parametrize(
    ("email", "status", "suppressed", "state"),
    [
        (None, "none", False, "dropped"),
        ("jane@acme.com", "valid", True, "dropped"),
        ("jane@acme.com", "invalid", False, "dropped"),
        ("info@acme.com", "valid", False, "hold"),
        ("jane@acme.com", "valid", False, "verified"),
        ("jane@acme.com", "catch_all", False, "needs_check"),
        ("jane@acme.com", "unknown", False, "needs_check"),
    ],
)
def test_decide(email: str | None, status: str, suppressed: bool, state: str) -> None:
    assert decide(email, status, suppressed)[0] == state


def test_needs_check_reason_says_what_happens_next() -> None:
    assert "re-check with Instantly" in decide("jane@acme.com", "catch_all", False)[1]
