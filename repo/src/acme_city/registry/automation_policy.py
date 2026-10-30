"""Pure policy decisions for governed registry auto-linking.

The matcher supplies a native score and explicit safety facts.  This module
never reads or writes the database: it only classifies the candidate as an
automatic application, a steward suggestion, or an ignored candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PolicyDecision(StrEnum):
    """The three outcomes produced by an automation policy."""

    AUTO_APPLY = "auto_apply"
    SUGGEST = "suggest"
    IGNORE = "ignore"


@dataclass(frozen=True)
class Thresholds:
    """Native-scale thresholds for one supported target family."""

    auto_apply: float
    suggest: float
    score_min: float = 0.0
    score_max: float = 1.0


DEFAULT_THRESHOLDS: dict[str, Thresholds] = {
    "owner_party": Thresholds(0.70, 0.30),
    "contractor_party": Thresholds(0.90, 0.30),
    "parcel": Thresholds(0.40, 0.40),
    "address": Thresholds(0.40, 0.35),
    "permit": Thresholds(1.00, 0.50),
    "address_locator": Thresholds(90.0, 80.0, 0.0, 100.0),
}

#: The record families whose automatic links this release may reverse.  A
#: family without a tested reversal is only ever suggested to a steward, so a
#: threshold never enables a link that cannot be taken back.
UNDO_SUPPORTED_FAMILIES: frozenset[str] = frozenset(
    {"owner_party", "contractor_party"}
)


def thresholds_for(family: str, stored: Any = None) -> Thresholds:
    """Return the thresholds of one family, from stored values or the defaults.

    The stored values are the thresholds of an activated policy.  A stored
    value that is missing or unreadable falls back to the default of the
    family, so a broken policy never widens the thresholds on its own.
    """
    default = DEFAULT_THRESHOLDS.get(family)
    if default is None:
        return Thresholds(auto_apply=1.0, suggest=0.0)
    if not isinstance(stored, dict):
        return default
    try:
        return Thresholds(
            auto_apply=float(stored["auto_apply"]),
            suggest=float(stored["suggest"]),
            score_min=default.score_min,
            score_max=default.score_max,
        )
    except (KeyError, TypeError, ValueError):
        return default


@dataclass(frozen=True)
class SafetyChecks:
    """Facts that a threshold is never allowed to override."""

    source_accepted_current: bool
    source_contract_eligible: bool
    target_exists_with_correct_type: bool
    identifier_namespace_known: bool
    required_identity_fields_present: bool
    no_identity_conflict: bool
    no_protected_manual_decision: bool
    comparison_current: bool
    no_active_link_replacement: bool
    undo_supported: bool
    permissions_granted: bool
    unique_target: bool
    corroborating_identity_evidence: bool

    def failures(self) -> tuple[str, ...]:
        """Return stable names for failed checks."""
        return tuple(
            name
            for name, passed in self.__dict__.items()
            if not passed
        )


@dataclass(frozen=True)
class PolicyEvaluation:
    """A deterministic classification with machine-readable reasons."""

    decision: PolicyDecision
    reasons: tuple[str, ...]
    thresholds: Thresholds


def evaluate_link(
    *,
    target_family: str,
    score: float | None,
    checks: SafetyChecks,
    next_best_score: float | None = None,
    thresholds: Thresholds | None = None,
) -> PolicyEvaluation:
    """Classify one candidate without side effects.

    Unsupported families are rejected instead of falling through to party
    matching.  Failed safety checks always require a steward when a candidate
    is actionable.  Party candidates additionally need a 0.20 score gap.
    """
    configured = thresholds or DEFAULT_THRESHOLDS.get(target_family)
    if configured is None:
        raise ValueError(f"unsupported automation target family: {target_family}")
    if configured.suggest > configured.auto_apply:
        raise ValueError("suggest threshold must not exceed auto apply threshold")
    if score is None:
        return PolicyEvaluation(PolicyDecision.IGNORE, ("no_candidate",), configured)
    if not configured.score_min <= score <= configured.score_max:
        raise ValueError(
            f"score must be between {configured.score_min:g} and {configured.score_max:g}"
        )

    failures = list(checks.failures())
    if target_family in {"owner_party", "contractor_party"} and next_best_score is not None:
        if not configured.score_min <= next_best_score <= configured.score_max:
            raise ValueError("next best score is outside the native score scale")
        if score - next_best_score < 0.20:
            failures.append("party_score_gap")

    if failures:
        return PolicyEvaluation(PolicyDecision.SUGGEST, tuple(failures), configured)
    if score >= configured.auto_apply:
        return PolicyEvaluation(PolicyDecision.AUTO_APPLY, ("eligible",), configured)
    if score >= configured.suggest:
        return PolicyEvaluation(PolicyDecision.SUGGEST, ("below_auto_apply_threshold",), configured)
    return PolicyEvaluation(PolicyDecision.IGNORE, ("below_suggest_threshold",), configured)


__all__ = [
    "DEFAULT_THRESHOLDS",
    "UNDO_SUPPORTED_FAMILIES",
    "PolicyDecision",
    "PolicyEvaluation",
    "SafetyChecks",
    "Thresholds",
    "evaluate_link",
    "thresholds_for",
]
