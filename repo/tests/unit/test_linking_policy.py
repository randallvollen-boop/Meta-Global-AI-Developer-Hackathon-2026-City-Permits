"""Pure linking policy decisions use native scales and mandatory checks."""

from __future__ import annotations

import pytest

from acme_city.registry.automation_policy import (
    PolicyDecision,
    SafetyChecks,
    Thresholds,
    evaluate_link,
)


@pytest.mark.parametrize(
    ("family", "score"),
    [
        ("owner_party", 0.70),
        ("contractor_party", 0.90),
        ("parcel", 0.40),
        ("address", 0.40),
        ("permit", 1.00),
        ("address_locator", 90.0),
    ],
)
def test_exact_auto_apply_thresholds_use_each_matchers_native_scale(family, score) -> None:
    assert evaluate_link(target_family=family, score=score).decision == PolicyDecision.AUTO_APPLY


def test_exact_suggestion_threshold_and_lower_score_are_distinct() -> None:
    assert evaluate_link(target_family="address", score=0.35).decision == PolicyDecision.SUGGEST
    assert evaluate_link(target_family="address", score=0.3499).decision == PolicyDecision.IGNORE


def test_party_ties_and_narrow_gaps_require_a_steward() -> None:
    tied = evaluate_link(target_family="owner_party", score=0.90, next_best_score=0.90)
    narrow = evaluate_link(target_family="owner_party", score=0.90, next_best_score=0.71)
    assert tied.decision == narrow.decision == PolicyDecision.SUGGEST
    assert tied.reasons == narrow.reasons == ("party_score_gap",)


def test_identity_conflicts_and_missing_fields_override_a_high_score() -> None:
    result = evaluate_link(
        target_family="contractor_party",
        score=1.0,
        checks=SafetyChecks(
            no_identity_conflict=False,
            required_identity_fields_present=False,
        ),
    )
    assert result.decision == PolicyDecision.SUGGEST
    assert set(result.reasons) == {"no_identity_conflict", "required_identity_fields_present"}


def test_exact_identifier_families_require_one_target() -> None:
    result = evaluate_link(
        target_family="parcel",
        score=0.40,
        checks=SafetyChecks(unique_target=False),
    )
    assert result.decision == PolicyDecision.SUGGEST
    assert result.reasons == ("unique_target",)


def test_missing_candidate_is_ignored_but_not_treated_as_a_link() -> None:
    result = evaluate_link(target_family="owner_party", score=None)
    assert result.decision == PolicyDecision.IGNORE
    assert result.reasons == ("no_candidate",)


def test_unsupported_types_and_invalid_policy_are_refused() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        evaluate_link(target_family="mystery", score=1.0)
    with pytest.raises(ValueError, match="suggest threshold"):
        evaluate_link(
            target_family="parcel",
            score=0.5,
            thresholds=Thresholds(auto_apply=0.4, suggest=0.5),
        )
    with pytest.raises(ValueError, match="between 0 and 1"):
        evaluate_link(target_family="parcel", score=40.0)
