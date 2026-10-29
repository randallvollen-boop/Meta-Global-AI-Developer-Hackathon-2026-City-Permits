"""Pure linking policy decisions use native scales and mandatory checks."""

from __future__ import annotations

from dataclasses import replace

import pytest

from acme_city.registry.automation_policy import (
    PolicyDecision,
    SafetyChecks,
    Thresholds,
    evaluate_link,
)


SAFE_CHECKS = SafetyChecks(
    source_accepted_current=True,
    source_contract_eligible=True,
    target_exists_with_correct_type=True,
    identifier_namespace_known=True,
    required_identity_fields_present=True,
    no_identity_conflict=True,
    no_protected_manual_decision=True,
    comparison_current=True,
    no_active_link_replacement=True,
    undo_supported=True,
    permissions_granted=True,
    unique_target=True,
    corroborating_identity_evidence=True,
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
    result = evaluate_link(target_family=family, score=score, checks=SAFE_CHECKS)
    assert result.decision == PolicyDecision.AUTO_APPLY


def test_exact_suggestion_threshold_and_lower_score_are_distinct() -> None:
    suggestion = evaluate_link(target_family="address", score=0.35, checks=SAFE_CHECKS)
    ignored = evaluate_link(target_family="address", score=0.3499, checks=SAFE_CHECKS)
    assert suggestion.decision == PolicyDecision.SUGGEST
    assert ignored.decision == PolicyDecision.IGNORE


def test_party_ties_and_narrow_gaps_require_a_steward() -> None:
    tied = evaluate_link(
        target_family="owner_party", score=0.90, checks=SAFE_CHECKS, next_best_score=0.90
    )
    narrow = evaluate_link(
        target_family="owner_party", score=0.90, checks=SAFE_CHECKS, next_best_score=0.71
    )
    assert tied.decision == narrow.decision == PolicyDecision.SUGGEST
    assert tied.reasons == narrow.reasons == ("party_score_gap",)


def test_identity_conflicts_and_missing_fields_override_a_high_score() -> None:
    result = evaluate_link(
        target_family="contractor_party",
        score=1.0,
        checks=replace(
            SAFE_CHECKS,
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
        checks=replace(SAFE_CHECKS, unique_target=False),
    )
    assert result.decision == PolicyDecision.SUGGEST
    assert result.reasons == ("unique_target",)


def test_missing_candidate_is_ignored_but_not_treated_as_a_link() -> None:
    result = evaluate_link(target_family="owner_party", score=None, checks=SAFE_CHECKS)
    assert result.decision == PolicyDecision.IGNORE
    assert result.reasons == ("no_candidate",)


def test_unsupported_types_and_invalid_policy_are_refused() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        evaluate_link(target_family="mystery", score=1.0, checks=SAFE_CHECKS)
    with pytest.raises(ValueError, match="suggest threshold"):
        evaluate_link(
            target_family="parcel",
            score=0.5,
            checks=SAFE_CHECKS,
            thresholds=Thresholds(auto_apply=0.4, suggest=0.5),
        )
    with pytest.raises(ValueError, match="between 0 and 1"):
        evaluate_link(target_family="parcel", score=40.0, checks=SAFE_CHECKS)
