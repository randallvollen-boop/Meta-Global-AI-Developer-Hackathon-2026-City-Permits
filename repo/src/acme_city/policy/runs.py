"""Run a scenario over a population and build the immutable snapshot.

``execute`` is a pure function over values: a frozen baseline, the typed
changes of one scenario revision and a population.  It returns an
:class:`ExecutedRun`, which holds everything a stored run needs and a
canonical content hash that never depends on an id or a timestamp that the
storage layer adds.  The service (``policy/service.py``) stores it; this
module reads and writes nothing.
"""
# REQUIRES: PER-02, REF-01
# A run snapshots its complete inputs and hashes their canonical content.

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from acme_city.policy import ENGINE_VERSION
from acme_city.policy.changes import (
    KIND_RULE_RETIREMENT,
    ChangeError,
    Scenario,
    ScenarioConfigResult,
    apply_scenario,
    change_to_mapping,
    parse_change,
)
from acme_city.policy.config import PolicyConfig, canonical_json, digest
from acme_city.policy.impact import ImpactResult, compute_impact
from acme_city.policy.population import (
    KIND_CURRENT,
    KIND_DECIDED_RANGE,
    KIND_SYNTHETIC_YEAR,
    Population,
)
from acme_city.policy.synthetic_feed import (
    RETROSPECTIVE_LABEL,
    SYNTHETIC_LABEL,
    SyntheticFilter,
    SyntheticYearFeed,
)

#: The version of the stored result document.  A change of its shape bumps it.
RESULT_VERSION = "policy-run-result-1"

SPEC_KINDS: tuple[str, ...] = (KIND_SYNTHETIC_YEAR, KIND_CURRENT, KIND_DECIDED_RANGE)

#: Defaults of the synthetic year form.
DEFAULT_SEED = 20261028
DEFAULT_COUNT = 600

#: The most changed cases a result document lists by name.  The counts are
#: always complete; only the named list is bounded.
MAX_LISTED_CASES = 500


def _plain(value: Any) -> Any:
    """Return ``value`` as plain JSON (tuples to lists, mappings to dicts)."""
    return json.loads(canonical_json(value))


class SpecError(ValueError):
    """Raised when a population request is malformed."""


@dataclass(frozen=True)
class PopulationSpec:
    """How a population is asked for."""

    kind: str = KIND_SYNTHETIC_YEAR
    seed: int = DEFAULT_SEED
    count: int = DEFAULT_COUNT
    range_start: str = ""
    range_end: str = ""
    permit_type: str = ""
    district: str = ""
    category: str = ""

    @property
    def filters(self) -> SyntheticFilter:
        return SyntheticFilter(self.permit_type, self.district, self.category)

    def canonical(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "seed": self.seed if self.kind == KIND_SYNTHETIC_YEAR else None,
            "count": self.count if self.kind == KIND_SYNTHETIC_YEAR else None,
            "range_start": self.range_start or None,
            "range_end": self.range_end or None,
            "permit_type": self.permit_type,
            "district": self.district,
            "category": self.category,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> PopulationSpec:
        kind = str(raw.get("kind") or KIND_SYNTHETIC_YEAR).strip()
        if kind not in SPEC_KINDS:
            raise SpecError(f"population kind {kind!r} is not one of {', '.join(SPEC_KINDS)}")

        def number(name: str, default: int) -> int:
            text = str(raw.get(name) if raw.get(name) not in (None, "") else default).strip()
            try:
                return int(text)
            except ValueError as error:
                raise SpecError(f"{name} must be a whole number") from error

        seed = number("seed", DEFAULT_SEED)
        count = number("count", DEFAULT_COUNT)
        start = str(raw.get("range_start") or "").strip()
        end = str(raw.get("range_end") or "").strip()
        if kind == KIND_DECIDED_RANGE:
            for label, text in (("start", start), ("end", end)):
                try:
                    datetime.fromisoformat(text)
                except ValueError as error:
                    raise SpecError(f"the {label} date must be a date like 2026-01-31") from error
            if end < start:
                raise SpecError("the end date must not be before the start date")
        return cls(
            kind=kind,
            seed=seed,
            count=count,
            range_start=start,
            range_end=end,
            permit_type=str(raw.get("permit_type") or "").strip(),
            district=str(raw.get("district") or "").strip(),
            category=str(raw.get("category") or "").strip(),
        )


def label_for(population: Population, spec: PopulationSpec) -> Population:
    """Return the population with its on-screen label set."""
    definition = population.definition
    if definition.kind == KIND_SYNTHETIC_YEAR:
        label = definition.label or SYNTHETIC_LABEL
    elif definition.kind == KIND_DECIDED_RANGE:
        label = f"{RETROSPECTIVE_LABEL} (decided {spec.range_start} to {spec.range_end})"
    else:
        label = f"{RETROSPECTIVE_LABEL} (current applications)"
    return replace(population, definition=replace(definition, label=label))


def narrow_stored(population: Population, spec: PopulationSpec) -> Population:
    """Narrow a stored population by permit type and district (zoning)."""
    if not (spec.permit_type or spec.district):
        return population
    chosen = tuple(
        case
        for case in population.cases
        if (not spec.permit_type or case.permit_type_key == spec.permit_type)
        and (not spec.district or case.parcel_map.get("parcel_zoning") == spec.district)
    )
    parts = []
    if spec.permit_type:
        parts.append(f"type {spec.permit_type}")
    if spec.district:
        parts.append(f"district {spec.district}")
    definition = replace(
        population.definition,
        label=f"{population.definition.display_label}, narrowed to {', '.join(parts)}",
    )
    return Population(definition, chosen)


def build_synthetic(spec: PopulationSpec) -> Population:
    """Build the synthetic-year population of a spec (no database)."""
    return label_for(
        SyntheticYearFeed(filters=spec.filters).build(seed=spec.seed, count=spec.count), spec
    )


@dataclass(frozen=True)
class ExecutedRun:
    """Everything a stored run holds, before storage adds ids and times."""

    scenario_name: str
    changes: tuple[dict[str, Any], ...]
    spec: PopulationSpec
    population: Population
    baseline: PolicyConfig
    scenario_result: ScenarioConfigResult
    impact: ImpactResult
    result: dict[str, Any]
    generator_version: str | None
    content_hash: str

    @property
    def case_inputs(self) -> list[dict[str, Any]]:
        return [case.canonical() for case in self.population.cases]


def scenario_from_changes(name: str, changes: Sequence[Mapping[str, Any]]) -> Scenario:
    """Read a stored scenario revision back into typed changes."""
    return Scenario(name=name, changes=tuple(parse_change(item) for item in changes))


def normalise_change(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return the stored mapping of one change request (raises ``ChangeError``)."""
    mapping = change_to_mapping(parse_change(raw))
    return {key: value for key, value in mapping.items() if value is not None}


def revision_content_hash(
    name: str, changes: Sequence[Mapping[str, Any]], starting: Mapping[str, Any] | None
) -> str:
    return digest(
        {"name": name, "changes": [dict(c) for c in changes], "starting_population": starting}
    )


def _count_by(items: Sequence[Any]) -> dict[str, int]:
    return dict(sorted(Counter(items).items()))


def result_document(impact: ImpactResult, scenario_result: ScenarioConfigResult) -> dict[str, Any]:
    """Return the stored result: the measures, the counts and the changed cases."""
    diffs = impact.case_diffs
    changed = [d for d in diffs if d.changed]
    listed = [
        {
            **d.to_dict(),
            "baseline_recommendation": d.baseline.recommendation,
            "scenario_recommendation": d.scenario.recommendation,
            "baseline_rule": d.baseline.rule_overall,
            "scenario_rule": d.scenario.rule_overall,
            "scenario_hold_reason": d.scenario.hold_reason,
        }
        for d in changed[:MAX_LISTED_CASES]
    ]
    added_hold_reasons = _count_by(
        [d.scenario.hold_reason or "" for d in diffs if d.scenario.is_hold and not d.baseline.is_hold]
    )
    applied = [
        {
            "change_index": a.change_index,
            "kind": a.change.kind,
            "target": a.target,
            "change": _plain(change_to_mapping(a.change)),
            "before": _plain(dict(a.before)),
            "after": _plain(dict(a.after)),
            "affected_type_keys": list(a.affected_type_keys),
            "citations": list(a.citations),
        }
        for a in scenario_result.applied
    ]
    return _plain(
        {
            "result_version": RESULT_VERSION,
            "population": {
                "label": impact.population_label,
                "kind": impact.population_kind,
                "synthetic": impact.population_synthetic,
                "retrospective": impact.population_retrospective,
                "size": impact.population_size,
            },
            "summary": impact.summary(),
            "outcome_counts": {
                "recommendation": {
                    "baseline": _count_by([d.baseline.recommendation for d in diffs]),
                    "scenario": _count_by([d.scenario.recommendation for d in diffs]),
                },
                "rule": {
                    "baseline": _count_by([d.baseline.rule_overall for d in diffs]),
                    "scenario": _count_by([d.scenario.rule_overall for d in diffs]),
                },
                "route": {
                    "baseline": _count_by([d.baseline.route_status for d in diffs]),
                    "scenario": _count_by([d.scenario.route_status for d in diffs]),
                },
            },
            "changed_cases": listed,
            "changed_case_total": len(changed),
            "changed_cases_truncated": len(changed) > MAX_LISTED_CASES,
            "added_hold_reasons": added_hold_reasons,
            "retires_a_rule": any(a["kind"] == KIND_RULE_RETIREMENT for a in applied),
            "applied_changes": applied,
            "notes": dict(impact.notes),
        }
    )


def content_hash_of(
    *,
    changes: Sequence[Mapping[str, Any]],
    scenario_name: str,
    baseline: PolicyConfig,
    proposed: PolicyConfig,
    population: Population,
    generator_version: str | None,
) -> str:
    """Hash the canonical content of a run (no id, no creation time)."""
    return digest(
        {
            "scenario": {"name": scenario_name, "changes": [dict(c) for c in changes]},
            "baseline": baseline.canonical(),
            "proposed": proposed.canonical(),
            "case_inputs": [case.canonical() for case in population.cases],
            "population": population.definition.canonical(),
            "analysis_at": baseline.analysis_at.isoformat(),
            "engine_version": ENGINE_VERSION,
            "generator_version": generator_version,
        }
    )


class UnsupportedScenario(ValueError):
    """Raised when a scenario holds a change this release does not support."""

    def __init__(self, result: ScenarioConfigResult) -> None:
        self.result = result
        parts = [r.message for r in result.unsupported] + [i.message for i in result.issues]
        super().__init__("; ".join(parts) or "the scenario was refused")


def execute(
    *,
    scenario_name: str,
    changes: Sequence[Mapping[str, Any]],
    baseline: PolicyConfig,
    spec: PopulationSpec,
    population: Population,
) -> ExecutedRun:
    """Score ``population`` under the baseline and the scenario, and snapshot it.

    Raises :class:`UnsupportedScenario` for a change this release does not
    support (nothing is run), and ``ValueError`` for an unusable population.
    """
    try:
        scenario = scenario_from_changes(scenario_name, changes)
    except ChangeError as error:
        raise ValueError(error.message) from error
    applied = apply_scenario(baseline, scenario)
    if applied.config is None:
        raise UnsupportedScenario(applied)
    impact = compute_impact(population, baseline, applied)
    generator = population.definition.generator_version
    return ExecutedRun(
        scenario_name=scenario_name,
        changes=tuple(dict(c) for c in changes),
        spec=spec,
        population=population,
        baseline=baseline,
        scenario_result=applied,
        impact=impact,
        result=result_document(impact, applied),
        generator_version=generator,
        content_hash=content_hash_of(
            changes=changes,
            scenario_name=scenario_name,
            baseline=baseline,
            proposed=applied.config,
            population=population,
            generator_version=generator,
        ),
    )


__all__ = [
    "DEFAULT_COUNT",
    "DEFAULT_SEED",
    "MAX_LISTED_CASES",
    "RESULT_VERSION",
    "SPEC_KINDS",
    "ExecutedRun",
    "PopulationSpec",
    "SpecError",
    "UnsupportedScenario",
    "build_synthetic",
    "content_hash_of",
    "execute",
    "label_for",
    "narrow_stored",
    "normalise_change",
    "result_document",
    "revision_content_hash",
    "scenario_from_changes",
]
