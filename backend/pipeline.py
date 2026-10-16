"""The one list everything follows: stages and lead states.

Plain tuples and a frozen dataclass. No registry, no base classes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    module: str
    built: bool
    reads: tuple[str, ...]
    writes: tuple[str, ...]


LEAD_STATES: tuple[str, ...] = (
    "sourced",
    "enriched",
    "verified",
    "needs_check",
    "hold",
    "personalized",
    "approved",
    "in_campaign",
    "replied",
    "bounced",
    "unsubscribed",
    "finished",
    "dropped",
)

STAGES: tuple[Stage, ...] = (
    Stage(
        "source",
        "Source companies",
        "backend.stages.source",
        True,
        (),
        ("sourced",),
    ),
    Stage(
        "enrich",
        "Enrich via Clay CSV",
        "backend.stages.enrich",
        True,
        ("sourced",),
        ("enriched", "verified", "needs_check", "hold", "dropped"),
    ),
    Stage(
        "verify",
        "Verify emails",
        "backend.stages.verify",
        True,
        ("enriched", "needs_check"),
        ("verified", "needs_check", "hold", "dropped"),
    ),
    Stage(
        "personalize",
        "Personalize",
        "backend.stages.personalize",
        False,
        ("verified",),
        ("personalized",),
    ),
    Stage(
        "qa",
        "QA approve",
        "backend.stages.qa",
        False,
        ("personalized",),
        ("approved", "hold"),
    ),
    Stage(
        "send",
        "Send to Instantly",
        "backend.stages.send",
        False,
        ("approved",),
        ("in_campaign",),
    ),
    Stage(
        "track",
        "Track outcomes",
        "backend.stages.track",
        False,
        ("in_campaign",),
        ("replied", "bounced", "unsubscribed", "finished"),
    ),
    Stage(
        "classify",
        "Classify replies",
        "backend.stages.classify",
        False,
        ("replied",),
        ("finished", "dropped"),
    ),
)
