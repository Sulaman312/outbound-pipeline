"""Decide what happens to each email Clay found. Pure functions: no database, no network.

Lead states written here:
  verified     Clay says valid. Ready for the next stage.
  needs_check  catch-all or unknown. Re-checked with Instantly's verifier before sending.
  hold         needs a decision first: role addresses like info@ wait on D5 in docs/plan.md.
  dropped      no email, invalid, or on the do-not-contact list. Never sent.
"""

from __future__ import annotations

import re

# Words Clay's validation providers use, mapped to our clay_status values.
_STATUS_WORDS = {
    "valid": "valid",
    "safe": "valid",
    "safe_to_send": "valid",
    "deliverable": "valid",
    "verified": "valid",
    "ok": "valid",
    "invalid": "invalid",
    "undeliverable": "invalid",
    "bad": "invalid",
    "catch_all": "catch_all",
    "catchall": "catch_all",
    "accept_all": "catch_all",
    "risky": "unknown",
    "unknown": "unknown",
}

ROLE_NAMES = frozenset(
    {
        "info", "contact", "hello", "hi", "sales", "support", "help", "admin", "office", "team",
        "hr", "jobs", "careers", "billing", "accounts", "accounting", "marketing", "enquiries",
        "inquiries", "mail", "service", "services", "noreply", "no-reply", "general", "reception",
    }
)  # fmt: skip


def clay_status(text: str | None, has_email: bool) -> str:
    """Turn whatever Clay's validation column says into valid, invalid, catch_all, unknown or none."""
    if not has_email:
        return "none"
    key = re.sub(r"[^a-z]+", "_", (text or "").strip().lower()).strip("_")
    if key in _STATUS_WORDS:
        return _STATUS_WORDS[key]
    if "catch" in key or "accept_all" in key:
        return "catch_all"
    if key.startswith("invalid") or key.startswith("undeliverable"):
        return "invalid"
    return "unknown"  # anything we don't recognise gets re-checked rather than trusted


def is_role_address(email: str) -> bool:
    return email.split("@", 1)[0] in ROLE_NAMES


def decide(email: str | None, status: str, suppressed: bool) -> tuple[str, str]:
    """(state, state_reason) for one person Clay returned."""
    if not email:
        return "dropped", "Clay found no email"
    if suppressed:
        return "dropped", "on the do-not-contact list"
    if status == "invalid":
        return "dropped", "Clay says invalid"
    if is_role_address(email):
        return "hold", "role address like info@ (waiting on decision D5)"
    if status == "valid":
        return "verified", "Clay says valid"
    return "needs_check", f"Clay says {status.replace('_', '-')}: re-check with Instantly"
