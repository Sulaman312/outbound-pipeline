"""pipeline.py: stage order and every lead state is used."""

from __future__ import annotations

from backend.pipeline import LEAD_STATES, STAGES


def test_stages_are_in_order() -> None:
    assert [stage.key for stage in STAGES] == [
        "source",
        "enrich",
        "verify",
        "personalize",
        "qa",
        "send",
        "track",
        "classify",
    ]


def test_only_first_three_stages_are_built() -> None:
    assert [stage.key for stage in STAGES if stage.built] == ["source", "enrich", "verify"]
    assert all(not stage.built for stage in STAGES[3:])


def test_every_lead_state_is_used() -> None:
    used: set[str] = set()
    for stage in STAGES:
        used.update(stage.reads)
        used.update(stage.writes)
    assert used == set(LEAD_STATES)


def test_lead_states_tuple_matches_expected() -> None:
    assert LEAD_STATES == (
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
