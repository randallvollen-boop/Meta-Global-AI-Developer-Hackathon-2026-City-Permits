"""Unit tests for the disposition of the adjudication agent.

The disposition is a pure function of the type, the rule results and the
state of the property of the case.  A case whose parcel the Data Steward has
not confirmed is never recommended on: the parcel inputs (zoning, flood zone)
come from that parcel, so the agent holds the case and waits for the steward.
"""

from __future__ import annotations

from acme_city.kernel.adjudication import (
    HOLD_PARCEL_UNCONFIRMED,
    OUTCOME_APPROVE,
    OUTCOME_CONDITIONS,
    OUTCOME_DENY,
    OUTCOME_HOLD,
    PARCEL_UNCONFIRMED_REASON,
    disposition,
)


def passing() -> list[dict[str, str]]:
    """Return one passing rule result."""
    return [{"rule_id": "DF-2", "status": "pass", "field_path": "height_ft"}]


def failing() -> list[dict[str, str]]:
    """Return one failing rule result."""
    return [{"rule_id": "DF-1", "status": "fail", "field_path": "height_ft"}]


def choose(*, results: list[dict[str, str]], conditions: list[str], parcel_confirmed: bool):
    """Return the disposition of one case."""
    return disposition(
        type_label="Residential deck or fence",
        discretionary=False,
        rule_count=2,
        results=results,
        conditions=conditions,
        parcel_confirmed=parcel_confirmed,
    )


def test_a_confirmed_parcel_recommends_approval() -> None:
    chosen = choose(results=passing(), conditions=[], parcel_confirmed=True)
    assert chosen.outcome == OUTCOME_APPROVE
    assert chosen.hold_reason is None
    assert "recommends approval" in chosen.reason


def test_an_unconfirmed_parcel_is_never_approved() -> None:
    chosen = choose(results=passing(), conditions=[], parcel_confirmed=False)
    assert chosen.outcome == OUTCOME_HOLD
    assert chosen.hold_reason == HOLD_PARCEL_UNCONFIRMED
    assert chosen.reason == PARCEL_UNCONFIRMED_REASON
    assert "Waiting on Data Steward" in chosen.reason


def test_an_unconfirmed_parcel_is_never_approved_with_conditions() -> None:
    chosen = choose(
        results=[{"rule_id": "DF-4", "status": "condition", "field_path": "height_ft"}],
        conditions=["DF-4: a footing inspection is required"],
        parcel_confirmed=False,
    )
    assert chosen.outcome == OUTCOME_HOLD
    assert chosen.hold_reason == HOLD_PARCEL_UNCONFIRMED


def test_a_failing_rule_still_recommends_denial() -> None:
    # The rule that fails does not read the parcel, so the failure stands
    # while the Data Steward confirms the property.
    chosen = choose(results=failing(), conditions=[], parcel_confirmed=False)
    assert chosen.outcome == OUTCOME_DENY
    assert "DF-1" in chosen.reason


def test_a_case_without_a_parcel_keeps_the_old_disposition() -> None:
    # The parameter defaults to a confirmed parcel, so every caller that does
    # not know about the property of a case behaves as it did.
    chosen = disposition(
        type_label="Residential deck or fence",
        discretionary=False,
        rule_count=2,
        results=passing(),
        conditions=[],
    )
    assert chosen.outcome == OUTCOME_APPROVE


def test_conditions_still_recommend_approval_with_conditions() -> None:
    chosen = choose(
        results=[{"rule_id": "DF-4", "status": "condition", "field_path": "height_ft"}],
        conditions=["DF-4: a footing inspection is required"],
        parcel_confirmed=True,
    )
    assert chosen.outcome == OUTCOME_CONDITIONS
