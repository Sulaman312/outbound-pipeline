"""Turning messy provider values into comparable ones.

Dedupe depends on this module: two records are the same company when their
normalised domains match, or, when neither has a domain, when their
normalised names match in the same country.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

# Hosts that are not a company's own website. A lead whose "website" is one of
# these has no usable domain (and so no domain for email finding either).
_NON_COMPANY_HOSTS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "tiktok.com",
    "google.com",
    "goo.gl",
    "linktr.ee",
    "wixsite.com",
    "sites.google.com",
    "business.site",
    "yelp.com",
    "booking.com",
    "calendly.com",
}

_LEGAL_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|ltd|limited|plc|pty|pty ltd|co|corp|"
    r"corporation|company|gmbh|ag|sa|sarl|bv|llp|lp)\b\.?",
    re.IGNORECASE,
)


def normalize_domain(value: str | None) -> str | None:
    """'https://www.Acme.com/about?x=1' -> 'acme.com'. Returns None if unusable."""
    if not value:
        return None
    value = value.strip().lower()
    if "@" in value:  # an email address was passed
        value = value.rsplit("@", 1)[1]
    if "//" not in value:
        value = "//" + value
    host = urlsplit(value).hostname or ""
    host = host.removeprefix("www.").strip(".")
    if not host or "." not in host:
        return None
    if any(host == bad or host.endswith("." + bad) for bad in _NON_COMPANY_HOSTS):
        return None
    return host


def normalize_name(name: str | None) -> str:
    """'Acme Software Pty. Ltd.' -> 'acme software'."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    text = _LEGAL_SUFFIXES.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def dedupe_key(domain: str | None, name: str | None, country: str) -> str:
    """Stable key for 'same company'. Domain wins; name+country is the fallback."""
    if domain:
        return f"d:{domain}"
    return f"n:{country.upper()}:{normalize_name(name)}"


def looks_like_limited_company(legal_name: str | None) -> bool:
    """UK rule from Section 1: email limited companies only (Ltd / Limited / PLC / LLP)."""
    if not legal_name:
        return False
    return bool(re.search(r"\b(ltd|limited|plc|llp)\b\.?", legal_name, re.IGNORECASE))
