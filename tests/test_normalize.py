"""normalize.py: domains and emails."""

from __future__ import annotations

import pytest

from outbound.normalize import normalize_domain, normalize_email


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("example.com", "example.com"),
        ("https://www.Example.com/about?x=1", "example.com"),
        ("http://example.com:8080", "example.com"),
        ("//www.example.com", "example.com"),
        ("WWW.EXAMPLE.CO.UK.", "example.co.uk"),
        ("shop.example.com", "shop.example.com"),
        ("  example.com  ", "example.com"),
        ("", None),
        (None, None),
        ("not a domain", None),
        ("localhost", None),
        ("http://", None),
    ],
)
def test_normalize_domain(value: str | None, expected: str | None) -> None:
    assert normalize_domain(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" Jane@Example.COM ", "jane@example.com"),
        ("jane@example", None),
        ("@example.com", None),
        ("jane doe@example.com", None),
        ("", None),
    ],
)
def test_normalize_email(value: str, expected: str | None) -> None:
    assert normalize_email(value) == expected
