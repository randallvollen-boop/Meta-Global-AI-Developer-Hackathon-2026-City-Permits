"""Pure adjudication producers: the hold findings and the recommendation.

The disposition is a function of the type's configuration, the number of
published rules and the rule results.  It never records anything.  A person
decides; the disposition only says what the agent would recommend.
"""
# REQUIRES: AI-03, PER-04, REF-01
# Discretionary types and missing rules are held for a person; otherwise the
# worst rule result sets the recommendation.

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from acme_city.kernel.findings import FindingSpec

#: The recommendation outcomes the adjudication agent may propose.
OUTCOME_HOLD = "hold"
OUTCOME_DENY = "deny"
OUTCOME_CONDITIONS = "approve_with_conditions"
OUTCOME_APPROVE = "approve"

#: The reason a hold is recorded for.
HOLD_DISCRETIONARY = "discretionary"
HOLD_NO_RULES = "no_rules"
HOLD_RULE_REVIEW = "rule_review"
HOLD_PARCEL_UNCONFIRMED = "parcel_unconfirmed"

#: What the agent says while the Data Steward has not confirmed the parcel.
#: The parcel inputs (zoning, flood zone) are read from the parcel the Data
#: Steward confirms, so a case whose property is still unresolved cannot be
#: recommended on.
PARCEL_UNCONFIRMED_REASON = (
    "Cannot recommend yet: the parcel is not confirmed. Waiting on Data Steward."
)


def hold_findings(
    *, type_label: str, discretionary: bool, rule_count: int
) -> tuple[FindingSpec, ...]:
    """Return the findings the rule loader records for a held type."""
    findings: list[FindingSpec] = []
    if discretionary:
        findings.append(
            FindingSpec(
                finding_type="judgment",
                message=(
                    f"{type_label} is a discretionary type, so it is decided by a "
                    "person or a board and never by an agent."
                ),
                rule="ACME Code §13-601",
                applicant_must="Wait for the board or the administrator to decide.",
                severity="review",
            )
        )
    if rule_count == 0:
        findings.append(
            FindingSpec(
                finding_type="judgment",
                message=(
                    f"No published rule applies to {type_label}, so no agent can "
                    "recommend an outcome."
                ),
                rule="ACME Code §13-602",
                applicant_must="Wait for a person to decide this application.",
                severity="review",
            )
        )
    return tuple(findings)


def conditions_of(results: Iterable[Mapping[str, Any]]) -> list[str]:
    """Collect the conditions of approval from the condition results."""
    conditions: list[str] = []
    for result in results:
        if str(result.get("status")) != "condition":
            continue
        note = str(result.get("condition_note") or result.get("message") or "").strip()
        rule_id = str(result.get("rule_id") or "rule")
        conditions.append(f"{rule_id}: {note}" if note else rule_id)
    return conditions


@dataclass(frozen=True)
class Disposition:
    """The recommendation the disposition node would record."""

    outcome: str
    reason: str
    hold_reason: str | None = None


def disposition(
    *,
    type_label: str,
    discretionary: bool,
    rule_count: int,
    results: Iterable[Mapping[str, Any]],
    conditions: Iterable[str],
    precedent_outcome: str | None = None,
    parcel_confirmed: bool = True,
) -> Disposition:
    """Choose the recommendation for a case.

    A discretionary type is held, a type without a rule is held, a result that
    needs judgement holds the case, any failure recommends denial, a case whose
    parcel the Data Steward has not confirmed is held, any condition recommends
    approval with conditions, else approval.
    """
    rows = list(results)
    condition_list = list(conditions)
    needs_judgment = [str(r.get("rule_id")) for r in rows if str(r.get("status")) == "review"]
    failing = [str(r.get("rule_id")) for r in rows if str(r.get("status")) == "fail"]
    hold_reason: str | None = None
    if discretionary:
        outcome = OUTCOME_HOLD
        hold_reason = HOLD_DISCRETIONARY
        reason = (
            f"{type_label} is discretionary, so the agent holds it for a person "
            "or a board."
        )
    elif not rule_count:
        outcome = OUTCOME_HOLD
        hold_reason = HOLD_NO_RULES
        reason = "No published rule applies, so the agent holds it for a person."
    elif needs_judgment:
        outcome = OUTCOME_HOLD
        hold_reason = HOLD_RULE_REVIEW
        reason = (
            f"Rule(s) {', '.join(needs_judgment)} need a person's judgement or a "
            "missing input, so the agent holds the case."
        )
    elif failing:
        outcome = OUTCOME_DENY
        reason = f"Rule(s) {', '.join(failing)} fail, so the agent recommends denial."
    elif not parcel_confirmed:
        # The parcel inputs (zoning, flood zone) come from the parcel the Data
        # Steward confirms.  Until the steward confirms the property, the case
        # is not evaluated on the whole rule set, so the agent does not
        # recommend approval; it waits for the steward.
        outcome = OUTCOME_HOLD
        hold_reason = HOLD_PARCEL_UNCONFIRMED
        reason = PARCEL_UNCONFIRMED_REASON
    elif condition_list:
        outcome = OUTCOME_CONDITIONS
        reason = (
            f"{len(condition_list)} condition(s) of approval apply, so the agent "
            "recommends approval with conditions."
        )
    else:
        outcome = OUTCOME_APPROVE
        reason = "Every applicable rule passes, so the agent recommends approval."
    if precedent_outcome is not None:
        reason += f" An earlier decided case on the same parcel was {precedent_outcome}."
    return Disposition(outcome=outcome, reason=reason, hold_reason=hold_reason)


__all__ = [
    "HOLD_DISCRETIONARY",
    "HOLD_NO_RULES",
    "HOLD_PARCEL_UNCONFIRMED",
    "HOLD_RULE_REVIEW",
    "OUTCOME_APPROVE",
    "OUTCOME_CONDITIONS",
    "OUTCOME_DENY",
    "OUTCOME_HOLD",
    "PARCEL_UNCONFIRMED_REASON",
    "Disposition",
    "conditions_of",
    "disposition",
    "hold_findings",
]
