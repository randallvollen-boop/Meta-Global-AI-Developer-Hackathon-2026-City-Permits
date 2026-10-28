"""Baseline versus scenario for every frozen case.

``compute_impact`` scores each case of a population twice (under the baseline
and under the scenario copy), compares the two outcomes and counts the
differences.  It reports, as separate figures:

* rule outcome changes (``fail->pass`` and so on) by permit type;
* recommendation changes, and recommendation holds cleared or added;
* needs-information routing at intake;
* findings added and removed, by permit type and finding type;
* service-target changes (the figures as configured; nothing is derived);
* hypothetical assessed fees (see :mod:`acme_city.policy.fees`);
* safety signals: every case that stops failing a rule, with the rule.

It computes **no** staff-days, no processing-time saving and no throughput:
there is no effort or capacity model to compute them from.
"""
# REQUIRES: PER-02, REF-01
# Counts come from re-scoring real frozen inputs twice; nothing is estimated.

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from acme_city.kernel.adjudication import (
    OUTCOME_APPROVE,
    OUTCOME_CONDITIONS,
    OUTCOME_DENY,
    OUTCOME_HOLD,
)
from acme_city.policy import ENGINE_VERSION
from acme_city.policy.changes import (
    AppliedChange,
    FeeChange,
    ScenarioConfigResult,
    ServiceTargetChange,
)
from acme_city.policy.config import PolicyConfig, digest
from acme_city.policy.fees import FeeImpact, fee_impact
from acme_city.policy.kernel import CaseOutcome, evaluate_case
from acme_city.policy.population import Population

DIRECTION_RELAXED = "relaxed"
DIRECTION_TIGHTENED = "tightened"
DIRECTION_UNCHANGED = "unchanged"
DIRECTION_OTHER = "changed_otherwise"

#: Lower is more permissive.
_RECOMMENDATION_RANK = {
    OUTCOME_APPROVE: 0,
    OUTCOME_CONDITIONS: 1,
    OUTCOME_HOLD: 2,
    OUTCOME_DENY: 3,
}
_RULE_RANK = {"pass": 0, "condition": 1, "review": 2, "fail": 3}
_ROUTE_RANK = {"ready_for_review": 0, "needs_information": 1}

#: What the result states about its own limits.
MEASURE_NOTES: dict[str, str] = {
    "rule_outcome": "Worst rule result of the case before and after (pass, condition, review, fail).",
    "recommendation": "What the adjudication agent would recommend; a person always decides.",
    "recommendation_holds": (
        "Cases the agent would hold for a person. A hold cleared is a case the agent "
        "would no longer hold; the decision, and every identity, parcel, credential, "
        "finance and missing-input safeguard, stay with the people and checks that "
        "own them."
    ),
    "needs_information": "Cases the intake router sends to early resolution instead of review.",
    "findings": "Findings the intake and adjudication producers would state, by type.",
    "service_targets": (
        "Service targets as configured, before and after. No processing time is derived from them."
    ),
    "fees": "Hypothetical assessed fees; not money collected and not a forecast of it.",
    "safety_signals": "Every case that stops failing a rule, with the rule, so a person can judge the risk.",
}


def case_direction(before: CaseOutcome, after: CaseOutcome) -> str:
    """Return whether the scenario relaxed or tightened one case."""
    pairs = (
        (_RECOMMENDATION_RANK.get(before.recommendation, 9),
         _RECOMMENDATION_RANK.get(after.recommendation, 9)),
        (_RULE_RANK.get(before.rule_overall, 9), _RULE_RANK.get(after.rule_overall, 9)),
        (_ROUTE_RANK.get(before.route_status, 9), _ROUTE_RANK.get(after.route_status, 9)),
    )
    for old, new in pairs:
        if new < old:
            return DIRECTION_RELAXED
        if new > old:
            return DIRECTION_TIGHTENED
    return DIRECTION_OTHER if _finding_keys(before) != _finding_keys(after) else DIRECTION_UNCHANGED


def _finding_keys(outcome: CaseOutcome) -> Counter[tuple[str, str]]:
    return Counter((f.finding_type, f.message) for f in outcome.all_findings)


def _rule_status_map(outcome: CaseOutcome) -> dict[str, dict[str, Any]]:
    return {str(r["rule_id"]): r for r in outcome.rule_results}


@dataclass(frozen=True)
class SafetySignal:
    """A case that stops failing a rule under the scenario."""

    case_ref: str
    permit_type_key: str
    rule_id: str
    citation: str
    observed_value: str | None
    baseline_limit: str | None
    scenario_limit: str | None
    rule_retired: bool
    scenario_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_ref": self.case_ref,
            "permit_type_key": self.permit_type_key,
            "rule_id": self.rule_id,
            "citation": self.citation,
            "observed_value": self.observed_value,
            "baseline_limit": self.baseline_limit,
            "scenario_limit": self.scenario_limit,
            "rule_retired": self.rule_retired,
            "scenario_status": self.scenario_status,
        }


@dataclass(frozen=True)
class CaseDiff:
    """The difference between two outcomes of one case."""

    case_ref: str
    permit_type_key: str
    direction: str
    rule_transition: str | None
    recommendation_transition: str | None
    route_transition: str | None
    findings_added: tuple[tuple[str, str], ...]
    findings_removed: tuple[tuple[str, str], ...]
    baseline: CaseOutcome
    scenario: CaseOutcome

    @property
    def changed(self) -> bool:
        return self.direction != DIRECTION_UNCHANGED

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_ref": self.case_ref,
            "permit_type_key": self.permit_type_key,
            "direction": self.direction,
            "rule_transition": self.rule_transition,
            "recommendation_transition": self.recommendation_transition,
            "route_transition": self.route_transition,
            "findings_added": [list(item) for item in self.findings_added],
            "findings_removed": [list(item) for item in self.findings_removed],
        }


def diff_case(before: CaseOutcome, after: CaseOutcome) -> CaseDiff:
    """Compare the baseline and scenario outcomes of one case."""
    old, new = _finding_keys(before), _finding_keys(after)
    added = tuple(sorted((new - old).elements()))
    removed = tuple(sorted((old - new).elements()))
    return CaseDiff(
        case_ref=before.case_ref,
        permit_type_key=before.permit_type_key,
        direction=case_direction(before, after),
        rule_transition=(
            None if before.rule_overall == after.rule_overall
            else f"{before.rule_overall}->{after.rule_overall}"
        ),
        recommendation_transition=(
            None if before.recommendation == after.recommendation
            else f"{before.recommendation}->{after.recommendation}"
        ),
        route_transition=(
            None if before.route_status == after.route_status
            else f"{before.route_status}->{after.route_status}"
        ),
        findings_added=added,
        findings_removed=removed,
        baseline=before,
        scenario=after,
    )


def safety_signals(diff: CaseDiff) -> list[SafetySignal]:
    """Return the rules a case stops failing under the scenario."""
    before = _rule_status_map(diff.baseline)
    after = _rule_status_map(diff.scenario)
    signals: list[SafetySignal] = []
    for rule_id in sorted(before):
        old = before[rule_id]
        if old.get("status") != "fail":
            continue
        new = after.get(rule_id)
        if new is not None and new.get("status") == "fail":
            continue
        signals.append(
            SafetySignal(
                case_ref=diff.case_ref,
                permit_type_key=diff.permit_type_key,
                rule_id=rule_id,
                citation=str(old.get("citation") or ""),
                observed_value=old.get("observed_value"),
                baseline_limit=old.get("limit_value"),
                scenario_limit=None if new is None else new.get("limit_value"),
                rule_retired=new is None,
                scenario_status="retired" if new is None else str(new.get("status")),
            )
        )
    return signals


@dataclass(frozen=True)
class ChangeImpact:
    """The counts attributable to one change applied alone to the baseline."""

    change_index: int
    kind: str
    target: str
    cases_evaluated: int
    cases_changed: int
    by_direction: tuple[tuple[str, int], ...]
    recommendation_transitions: tuple[tuple[str, int], ...]
    rule_transitions: tuple[tuple[str, int], ...]
    models_case_outcomes: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_index": self.change_index,
            "kind": self.kind,
            "target": self.target,
            "cases_evaluated": self.cases_evaluated,
            "cases_changed": self.cases_changed,
            "by_direction": dict(self.by_direction),
            "recommendation_transitions": dict(self.recommendation_transitions),
            "rule_transitions": dict(self.rule_transitions),
            "models_case_outcomes": self.models_case_outcomes,
        }


@dataclass(frozen=True)
class ServiceTargetDelta:
    permit_type_key: str
    before_days: int
    after_days: int
    cases_in_population: int


@dataclass(frozen=True)
class ImpactResult:
    """Everything a run reports.  Immutable, and hashed without ids or times."""

    engine_version: str
    analysis_at: datetime
    population_label: str
    population_kind: str
    population_synthetic: bool
    population_retrospective: bool
    population_size: int
    population_hash: str
    baseline_hash: str
    scenario_hash: str
    scenario_config_hash: str
    case_diffs: tuple[CaseDiff, ...]
    changed_case_count: int
    by_direction: tuple[tuple[str, int], ...]
    rule_transitions_by_type: tuple[tuple[str, str, int], ...]
    recommendation_transitions: tuple[tuple[str, int], ...]
    findings_added: tuple[tuple[str, str, int], ...]
    findings_removed: tuple[tuple[str, str, int], ...]
    holds: dict[str, int]
    needs_information: dict[str, int]
    service_targets: tuple[ServiceTargetDelta, ...]
    by_change: tuple[ChangeImpact, ...]
    safety_signals: tuple[SafetySignal, ...]
    fees: FeeImpact | None
    notes: dict[str, str]

    @property
    def result_hash(self) -> str:
        return digest(self.canonical())

    def canonical(self) -> dict[str, Any]:
        return {
            "engine_version": self.engine_version,
            "analysis_at": self.analysis_at.isoformat(),
            "population": {
                "label": self.population_label,
                "kind": self.population_kind,
                "synthetic": self.population_synthetic,
                "size": self.population_size,
                "hash": self.population_hash,
            },
            "baseline_hash": self.baseline_hash,
            "scenario_hash": self.scenario_hash,
            "scenario_config_hash": self.scenario_config_hash,
            "summary": self.summary(),
            "cases": [d.to_dict() for d in self.case_diffs if d.changed],
            "baseline_outcomes": [d.baseline.canonical() for d in self.case_diffs],
            "scenario_outcomes": [d.scenario.canonical() for d in self.case_diffs],
        }

    def summary(self) -> dict[str, Any]:
        """The measures, as plain JSON-ready values."""
        return {
            "changed_case_count": self.changed_case_count,
            "by_direction": dict(self.by_direction),
            "rule_transitions_by_type": [list(item) for item in self.rule_transitions_by_type],
            "recommendation_transitions": dict(self.recommendation_transitions),
            "findings_added": [list(item) for item in self.findings_added],
            "findings_removed": [list(item) for item in self.findings_removed],
            "holds": dict(self.holds),
            "needs_information": dict(self.needs_information),
            "service_targets": [
                {
                    "permit_type_key": s.permit_type_key,
                    "before_days": s.before_days,
                    "after_days": s.after_days,
                    "cases_in_population": s.cases_in_population,
                }
                for s in self.service_targets
            ],
            "by_change": [c.to_dict() for c in self.by_change],
            "safety_signals": [s.to_dict() for s in self.safety_signals],
            "fees": None if self.fees is None else self.fees.to_dict(),
        }


def _score(population: Population, config: PolicyConfig) -> list[CaseOutcome]:
    return [evaluate_case(case, config) for case in population.cases]


def _change_impact(
    applied: AppliedChange,
    population: Population,
    baseline: PolicyConfig,
    baseline_outcomes: list[CaseOutcome],
    scenario: ScenarioConfigResult,
) -> ChangeImpact:
    """Apply one change alone and count its effect (a change on its own)."""
    from acme_city.policy.changes import Scenario, apply_scenario

    models = not isinstance(applied.change, (FeeChange, ServiceTargetChange))
    single = apply_scenario(
        baseline, Scenario(name=scenario.scenario.name, changes=(applied.change,))
    )
    by_direction: Counter[str] = Counter()
    recs: Counter[str] = Counter()
    rules: Counter[str] = Counter()
    changed = 0
    if single.config is not None and models:
        for case, before in zip(population.cases, baseline_outcomes, strict=True):
            diff = diff_case(before, evaluate_case(case, single.config))
            if diff.changed:
                changed += 1
                by_direction[diff.direction] += 1
                if diff.recommendation_transition:
                    recs[diff.recommendation_transition] += 1
                if diff.rule_transition:
                    rules[diff.rule_transition] += 1
    return ChangeImpact(
        change_index=applied.change_index,
        kind=applied.change.kind,
        target=applied.target,
        cases_evaluated=population.size,
        cases_changed=changed,
        by_direction=tuple(sorted(by_direction.items())),
        recommendation_transitions=tuple(sorted(recs.items())),
        rule_transitions=tuple(sorted(rules.items())),
        models_case_outcomes=models,
    )


def compute_impact(
    population: Population,
    baseline: PolicyConfig,
    scenario: ScenarioConfigResult,
) -> ImpactResult:
    """Re-score ``population`` under the baseline and the scenario and diff them.

    Raises ``ValueError`` if the population is unusable or the scenario was
    refused (an unsupported or invalid change): there is nothing to compute.
    """
    if scenario.config is None:
        raise ValueError("the scenario was refused; there is no scenario configuration to run")
    if scenario.baseline_hash != baseline.config_hash:
        raise ValueError("the scenario was built on a different baseline")
    problems = population.validate(baseline)
    if problems:
        raise ValueError("; ".join(problems))
    before_all = _score(population, baseline)
    after_all = _score(population, scenario.config)
    diffs = tuple(diff_case(b, a) for b, a in zip(before_all, after_all, strict=True))

    by_direction: Counter[str] = Counter()
    rule_by_type: Counter[tuple[str, str]] = Counter()
    recs: Counter[str] = Counter()
    added: Counter[tuple[str, str]] = Counter()
    removed: Counter[tuple[str, str]] = Counter()
    signals: list[SafetySignal] = []
    for diff in diffs:
        if diff.changed:
            by_direction[diff.direction] += 1
        if diff.rule_transition:
            rule_by_type[(diff.permit_type_key, diff.rule_transition)] += 1
        if diff.recommendation_transition:
            recs[diff.recommendation_transition] += 1
        for finding_type, _message in diff.findings_added:
            added[(diff.permit_type_key, finding_type)] += 1
        for finding_type, _message in diff.findings_removed:
            removed[(diff.permit_type_key, finding_type)] += 1
        signals.extend(safety_signals(diff))

    holds_before = sum(1 for d in diffs if d.baseline.is_hold)
    holds_after = sum(1 for d in diffs if d.scenario.is_hold)
    cleared = [d for d in diffs if d.baseline.is_hold and not d.scenario.is_hold]
    added_holds = [d for d in diffs if d.scenario.is_hold and not d.baseline.is_hold]
    holds = {
        "baseline": holds_before,
        "scenario": holds_after,
        "cleared": len(cleared),
        "added": len(added_holds),
        "cleared_discretionary": sum(
            1 for d in cleared if d.baseline.hold_reason == "discretionary"
        ),
        "cleared_but_still_blocked_by_safeguards": sum(
            1 for d in cleared if d.scenario.safeguards or d.scenario.missing_required_inputs
        ),
    }
    needs = {
        "baseline": sum(1 for d in diffs if d.baseline.needs_information),
        "scenario": sum(1 for d in diffs if d.scenario.needs_information),
        "cleared": sum(
            1 for d in diffs if d.baseline.needs_information and not d.scenario.needs_information
        ),
        "added": sum(
            1 for d in diffs if d.scenario.needs_information and not d.baseline.needs_information
        ),
    }
    target_deltas: list[ServiceTargetDelta] = []
    for item in baseline.permit_types:
        new = scenario.config.type_config(item.key)
        if new is not None and new.service_target_days != item.service_target_days:
            target_deltas.append(
                ServiceTargetDelta(
                    item.key,
                    item.service_target_days,
                    new.service_target_days,
                    sum(1 for case in population.cases if case.permit_type_key == item.key),
                )
            )
    by_change = tuple(
        _change_impact(applied, population, baseline, before_all, scenario)
        for applied in scenario.applied
    )
    has_fee_change = any(isinstance(a.change, FeeChange) for a in scenario.applied)
    fees = fee_impact(population.cases, baseline, scenario) if has_fee_change else None
    definition = population.definition
    return ImpactResult(
        engine_version=ENGINE_VERSION,
        analysis_at=baseline.analysis_at,
        population_label=definition.display_label,
        population_kind=definition.kind,
        population_synthetic=definition.synthetic,
        population_retrospective=definition.retrospective,
        population_size=population.size,
        population_hash=population.population_hash,
        baseline_hash=baseline.config_hash,
        scenario_hash=scenario.scenario.scenario_hash,
        scenario_config_hash=scenario.config.config_hash,
        case_diffs=diffs,
        changed_case_count=sum(by_direction.values()),
        by_direction=tuple(sorted(by_direction.items())),
        rule_transitions_by_type=tuple(sorted((k, t, n) for (k, t), n in rule_by_type.items())),
        recommendation_transitions=tuple(sorted(recs.items())),
        findings_added=tuple(sorted((k, t, n) for (k, t), n in added.items())),
        findings_removed=tuple(sorted((k, t, n) for (k, t), n in removed.items())),
        holds=holds,
        needs_information=needs,
        service_targets=tuple(target_deltas),
        by_change=by_change,
        safety_signals=tuple(signals),
        fees=fees,
        notes=dict(MEASURE_NOTES),
    )


__all__ = [
    "DIRECTION_OTHER",
    "DIRECTION_RELAXED",
    "DIRECTION_TIGHTENED",
    "DIRECTION_UNCHANGED",
    "MEASURE_NOTES",
    "CaseDiff",
    "ChangeImpact",
    "ImpactResult",
    "SafetySignal",
    "ServiceTargetDelta",
    "case_direction",
    "compute_impact",
    "diff_case",
    "safety_signals",
]
