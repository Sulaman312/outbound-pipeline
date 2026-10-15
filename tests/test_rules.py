"""rules.py: reading Clay's email check, and the ready / maybe / hold / drop decision."""

from __future__ import annotations

import pytest

from outbound.rules import clay_status, decide, is_role_address


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
    ("email", "status", "suppressed", "decision"),
    [
        (None, "none", False, "drop"),
        ("jane@acme.com", "valid", True, "drop"),
        ("jane@acme.com", "invalid", False, "drop"),
        ("info@acme.com", "valid", False, "hold"),
        ("jane@acme.com", "valid", False, "ready"),
        ("jane@acme.com", "catch_all", False, "maybe"),
        ("jane@acme.com", "unknown", False, "maybe"),
    ],
)
def test_decide(email: str | None, status: str, suppressed: bool, decision: str) -> None:
    assert decide(email, status, suppressed)[0] == decision


def test_maybe_reason_says_what_happens_next() -> None:
    assert "re-check with Instantly" in decide("jane@acme.com", "catch_all", False)[1]
