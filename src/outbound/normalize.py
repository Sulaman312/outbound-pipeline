"""Turn websites, domains and emails into one normal form so duplicates are easy to spot."""

from __future__ import annotations

import re

_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def normalize_domain(value: str | None) -> str | None:
    """'https://www.Example.com/about' -> 'example.com'. Returns None if it isn't a domain."""
    if not value:
        return None
    text = value.strip().lower()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.lstrip("/")
    for separator in ("/", "?", "#"):
        text = text.split(separator, 1)[0]
    text = text.rsplit("@", 1)[-1]  # drops user@ parts
    text = text.split(":", 1)[0].rstrip(".")  # drops ports and a trailing dot
    if text.startswith("www."):
        text = text[4:]
    return text if _DOMAIN.match(text) else None


def normalize_email(value: str | None) -> str | None:
    """' Jane@Example.COM ' -> 'jane@example.com'. Returns None if it isn't an email."""
    if not value:
        return None
    text = value.strip().lower()
    local, at, domain = text.rpartition("@")
    if not at or not local or " " in local or normalize_domain(domain) != domain:
        return None
    return text
