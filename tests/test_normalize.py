import pytest

from outbound.normalize import (
    dedupe_key,
    looks_like_limited_company,
    normalize_domain,
    normalize_name,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://www.Acme.com/about?x=1", "acme.com"),
        ("acme.co.uk", "acme.co.uk"),
        ("http://shop.acme.com.au/", "shop.acme.com.au"),
        ("jane@acme.io", "acme.io"),
        ("https://www.facebook.com/acmeclinic", None),
        ("https://acme.wixsite.com/home", None),
        ("", None),
        (None, None),
        ("localhost", None),
    ],
)
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected


def test_normalize_name_strips_legal_suffix_and_punctuation():
    assert normalize_name("Acme Software Pty. Ltd.") == "acme software"
    assert normalize_name("Acme, Inc.") == "acme"
    assert normalize_name("Zürich Dental GmbH") == "zurich dental"


def test_dedupe_key_prefers_domain():
    assert dedupe_key("acme.com", "Acme", "US") == "d:acme.com"
    assert dedupe_key(None, "Acme Ltd", "uk") == "n:UK:acme"


def test_limited_company():
    assert looks_like_limited_company("Acme Software Ltd")
    assert looks_like_limited_company("ACME LIMITED")
    assert not looks_like_limited_company("John Smith Physio")
    assert not looks_like_limited_company(None)
