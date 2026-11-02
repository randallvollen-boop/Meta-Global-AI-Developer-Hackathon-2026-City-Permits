"""Unit tests for the plain reason of a recommendation.

The helper words a recommendation: the outcome first, then the reason with the
rule's own message, title and citation and the submitted value against the
limit.  It never decides, and it never shows a bare rule id.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acme_city.agents.plain_reason import (
    condition_line,
    describe_recommendation,
    plain_reason,
)

RULES = {
    rule["rule_id"]: rule
    for rule in json.loads(
        (Path(__file__).resolve().parents[2] / "config" / "rules_and_fees.json").read_text()
    )["rules"]
}


def row(rule_id: str, status: str, observed: object, **extra: object) -> dict[str, object]:
    """Return one evaluator row built from the published rule."""
    rule = RULES[rule_id]
    return {
        "rule_id": rule_id,
        "status": status,
        "operator": rule["operator"],
        "observed_value": observed,
        "limit_value": rule["limit_value"],
        "field_path": rule["field_path"],
        "citation": rule["citation"],
        "message": rule["message"],
        "condition_note": rule["condition_note"],
        "title": rule["title"],
        **extra,
    }


def test_df1_denial_says_the_value_against_the_limit_and_what_would_change() -> None:
    reason = plain_reason(
        outcome="deny", hold_reason=None, results=[row("DF-1", "fail", "6")]
    )
    assert reason.short == (
        "Recommend deny: the front yard fence is 6 ft; the limit is 4 ft "
        "(ACME Code §14-305, Fence height, front yard)."
    )
    assert reason.rest == (
        "A fence of 4 ft or lower, or a variance, would meet the rule.",
    )


def test_df2_denial_names_the_side_and_rear_rule() -> None:
    reason = plain_reason(
        outcome="deny", hold_reason=None, results=[row("DF-2", "fail", "7")]
    )
    assert reason.short == (
        "Recommend deny: the side or rear yard fence is 7 ft; the limit is 6 ft "
        "(ACME Code §14-306, Fence height, side and rear yard)."
    )


def test_df3_denial_uses_the_minimum() -> None:
    reason = plain_reason(
        outcome="deny", hold_reason=None, results=[row("DF-3", "fail", "5")]
    )
    assert reason.short == (
        "Recommend deny: the deck rear setback is 5 ft; the minimum is 8 ft "
        "(ACME Code §14-308, Deck rear setback)."
    )
    assert reason.rest == (
        "A setback of 8 ft or more, or a variance, would meet the rule.",
    )


def test_several_failing_rules_are_listed_one_per_line() -> None:
    reason = plain_reason(
        outcome="deny",
        hold_reason=None,
        results=[row("DF-1", "fail", "6"), row("DF-3", "fail", "5")],
    )
    assert reason.short == "Recommend deny: 2 rules are not met."
    assert len(reason.rest) == 2
    assert "Fence height, front yard" in reason.rest[0]
    assert "Deck rear setback" in reason.rest[1]


def test_df4_condition_names_the_rule_and_its_note() -> None:
    reason = plain_reason(
        outcome="approve_with_conditions",
        hold_reason=None,
        results=[row("DF-4", "condition", "3"), row("DF-3", "pass", "9")],
    )
    assert reason.short.startswith("Recommend approve with conditions: ")
    assert (
        "Condition: Footing inspection and guard rail required "
        "(ACME Code §14-311, Deck footing inspection)."
    ) in reason.rest
    assert any("Deck rear setback" in line for line in reason.rest)


def test_an_approval_lists_the_rules_that_passed_in_one_line() -> None:
    reason = plain_reason(
        outcome="approve",
        hold_reason=None,
        results=[row("DF-2", "pass", "5"), row("DF-3", "pass", "9")],
    )
    assert reason.lines == (
        "Recommend approve: all 2 rules that apply pass: "
        "ACME Code §14-306, Fence height, side and rear yard; "
        "ACME Code §14-308, Deck rear setback.",
    )


def test_an_unconfirmed_parcel_says_what_was_not_checked() -> None:
    reason = plain_reason(
        outcome="approve",
        hold_reason=None,
        results=[
            row("DF-2", "pass", "5"),
            {
                "rule_id": "FZ-1",
                "status": "review",
                "reason": "parcel_not_confirmed",
                "title": "Flood zone",
            },
        ],
        parcel_confirmed=False,
    )
    assert reason.lines == (
        "Recommend approve: the one rule that applies passes: "
        "ACME Code §14-306, Fence height, side and rear yard.",
        "Not checked: Flood zone, because the parcel is not confirmed.",
    )


def test_a_denial_on_an_unconfirmed_parcel_still_says_what_was_not_checked() -> None:
    reason = plain_reason(
        outcome="deny",
        hold_reason=None,
        results=[
            row("DF-1", "fail", "6"),
            {
                "rule_id": "FZ-1",
                "status": "review",
                "reason": "parcel_not_confirmed",
                "title": "Flood zone",
            },
        ],
        parcel_confirmed=False,
    )
    assert reason.lines[-1] == "Not checked: Flood zone, because the parcel is not confirmed."


def test_the_earlier_case_is_one_line_of_its_own() -> None:
    reason = plain_reason(
        outcome="hold",
        hold_reason="discretionary",
        results=[],
        kernel_reason=(
            "A sign is discretionary, so the agent holds it for a person or a board. "
            "An earlier decided case on the same parcel was approved."
        ),
        precedent_outcome="approved",
    )
    assert reason.lines == (
        "A sign is discretionary, so the agent holds it for a person or a board.",
        "An earlier decided case on the same parcel was approved.",
    )


def test_a_missing_value_is_stated_with_its_rule() -> None:
    required = next(
        (rule for rule in RULES.values() if rule["operator"] == "required" and rule["on_violate"] == "fail"),
    )
    rule_id = required["rule_id"]
    reason = plain_reason(
        outcome="deny", hold_reason=None, results=[row(rule_id, "fail", None)]
    )
    assert "No value was submitted" in reason.short
    assert required["title"] in reason.short


def test_a_conditions_rule_id_is_replaced_by_its_title() -> None:
    line = condition_line(
        "DF-4: Footing inspection and guard rail required",
        [row("DF-4", "condition", "3")],
    )
    assert line == (
        "Footing inspection and guard rail required (ACME Code §14-311, Deck footing inspection)."
    )


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_no_rule_of_the_catalogue_shows_a_bare_id(rule_id: str) -> None:
    rule = RULES[rule_id]
    status = {"fail": "fail", "condition": "condition", "judgment": "review"}[rule["on_violate"]]
    outcome = {"fail": "deny", "condition": "approve_with_conditions", "review": "hold"}[status]
    observed = "99" if rule["operator"] == "max" else "0"
    reason = plain_reason(
        outcome=outcome,
        hold_reason="rule_review" if status == "review" else None,
        results=[row(rule_id, status, observed)],
        kernel_reason="held",
    )
    assert rule_id not in reason.text
    assert rule["citation"] in reason.text or status == "review"


def test_a_recorded_recommendation_is_described_for_every_screen() -> None:
    evidence = [row("DF-1", "fail", "6", unit="ft")]
    view = describe_recommendation(
        rationale="Recommend deny: x.\nMore.",
        evidence_refs=evidence,
        conditions=["DF-4: Footing inspection and guard rail required"],
        titles={"DF-4": "Deck footing inspection"},
    )
    assert view["short"] == "Recommend deny: x."
    assert view["rest"] == ["More."]
    assert view["conditions"] == [
        "Footing inspection and guard rail required (Deck footing inspection)."
    ]
    assert view["evidence"] == [
        "Fence height, front yard: does not pass, submitted 6 ft, limit 4 ft, ACME Code §14-305"
    ]
