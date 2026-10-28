"""The fee kernel: hypothetical assessed fees under a baseline and a scenario.

It prices a frozen case the way the finance service assesses a stored one: the
latest published schedule in force on the case's basis date
(:func:`acme_city.kernel.selection.select_assessment_schedule`) and the exact
decimal arithmetic of :func:`acme_city.finance.calculator.calculate_fee`.

Only a fixed charge and a valuation multiplier can change.  A case without a
usable valuation (or without a schedule in force) cannot be priced; it is
listed on its own and counted in neither total.  The totals are
**hypothetical assessed fees** for the cases in the population.  They are not
money collected and not a forecast of it.
"""
# REQUIRES: FIN-01, FIN-02
# Fees are calculated with the production schedule selection and exact
# rounding; unpriceable cases are reported separately.

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from acme_city.finance.calculator import MoneyError, calculate_fee, format_cents
from acme_city.kernel.inputs import declared_valuation_cents
from acme_city.kernel.selection import select_assessment_schedule
from acme_city.policy.changes import FEE_FIXED_KEY, FEE_MULTIPLIER_KEY, FeeChange, ScenarioConfigResult
from acme_city.policy.config import PolicyConfig
from acme_city.policy.population import CaseInput

#: The label every total carries.
TOTAL_LABEL = "hypothetical assessed fees"
TOTAL_NOTE = (
    "Hypothetical assessed fees for the cases in this population, calculated "
    "with the published fee schedule arithmetic. They are not money collected "
    "and not a forecast of it."
)

UNPRICEABLE_NO_VALUATION = "no_valuation"
UNPRICEABLE_INVALID_VALUATION = "invalid_valuation"
UNPRICEABLE_NO_SCHEDULE = "no_fee_schedule_in_force"
UNPRICEABLE_INVALID_SCHEDULE = "invalid_fee_schedule"


@dataclass(frozen=True)
class CaseFee:
    """The hypothetical assessed fee of one case under one configuration."""

    case_ref: str
    permit_type_key: str
    priceable: bool
    reason: str | None = None
    fee_schedule_id: str | None = None
    version_label: str | None = None
    valuation_cents: int | None = None
    fixed_cents: int | None = None
    variable_cents: int | None = None
    total_cents: int | None = None


def price_case(case: CaseInput, config: PolicyConfig) -> CaseFee:
    """Return the hypothetical assessed fee of ``case`` under ``config``."""
    cents, reason = declared_valuation_cents(case.facts_map)
    if cents is None:
        return CaseFee(case.case_ref, case.permit_type_key, False, reason)
    schedule = select_assessment_schedule(config.fee_schedules, case.basis_at)
    if schedule is None:
        return CaseFee(
            case.case_ref, case.permit_type_key, False, UNPRICEABLE_NO_SCHEDULE,
            valuation_cents=cents,
        )
    try:
        assessment = calculate_fee(
            schedule.definition,
            cents,
            currency=schedule.currency,
            fee_schedule_id=schedule.fee_schedule_id,
            version_label=schedule.version_label,
        )
    except (MoneyError, ValueError, TypeError):
        return CaseFee(
            case.case_ref, case.permit_type_key, False, UNPRICEABLE_INVALID_SCHEDULE,
            fee_schedule_id=schedule.fee_schedule_id, version_label=schedule.version_label,
            valuation_cents=cents,
        )
    fixed, variable = assessment.lines[0].amount_cents, assessment.lines[1].amount_cents
    return CaseFee(
        case.case_ref, case.permit_type_key, True, None,
        schedule.fee_schedule_id, schedule.version_label, cents, fixed, variable,
        assessment.total_cents,
    )


@dataclass(frozen=True)
class TypeFeeTotals:
    permit_type_key: str
    priced: int
    baseline_cents: int
    scenario_cents: int

    @property
    def delta_cents(self) -> int:
        return self.scenario_cents - self.baseline_cents


@dataclass(frozen=True)
class FeeImpact:
    """Baseline versus scenario hypothetical assessed fees for a population."""

    label: str
    note: str
    changed_schedule_ids: tuple[str, ...]
    #: Every type whose configuration names a changed schedule.
    types_sharing_changed_schedule: tuple[str, ...]
    #: Every type with at least one case priced by a changed schedule.  The
    #: finance selection does not filter by type, so this can be wider.
    types_priced_by_changed_schedule: tuple[str, ...]
    priced_count: int
    baseline_total_cents: int
    scenario_total_cents: int
    by_type: tuple[TypeFeeTotals, ...]
    #: ``(case_ref, permit_type_key, reason)`` for every case that cannot be priced.
    unpriceable: tuple[tuple[str, str, str], ...]
    changed_case_count: int

    @property
    def delta_cents(self) -> int:
        return self.scenario_total_cents - self.baseline_total_cents

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "note": self.note,
            "changed_schedule_ids": list(self.changed_schedule_ids),
            "types_sharing_changed_schedule": list(self.types_sharing_changed_schedule),
            "types_priced_by_changed_schedule": list(self.types_priced_by_changed_schedule),
            "priced_count": self.priced_count,
            "changed_case_count": self.changed_case_count,
            "baseline_total_cents": self.baseline_total_cents,
            "scenario_total_cents": self.scenario_total_cents,
            "delta_cents": self.delta_cents,
            "baseline_total": format_cents(self.baseline_total_cents),
            "scenario_total": format_cents(self.scenario_total_cents),
            "delta": format_cents(self.delta_cents),
            "by_type": [
                {
                    "permit_type_key": row.permit_type_key,
                    "priced": row.priced,
                    "baseline_cents": row.baseline_cents,
                    "scenario_cents": row.scenario_cents,
                    "delta_cents": row.delta_cents,
                }
                for row in self.by_type
            ],
            "unpriceable": [
                {"case_ref": ref, "permit_type_key": key, "reason": reason}
                for ref, key, reason in self.unpriceable
            ],
        }


def fee_impact(
    cases: tuple[CaseInput, ...],
    baseline: PolicyConfig,
    scenario: ScenarioConfigResult,
) -> FeeImpact:
    """Price ``cases`` under the baseline and under the scenario copy."""
    if scenario.config is None:
        raise ValueError("a scenario that was not applied cannot be priced")
    changed = tuple(
        sorted(
            {
                change.change.fee_schedule_id
                for change in scenario.applied
                if isinstance(change.change, FeeChange)
            }
        )
    )
    sharing = tuple(
        sorted(
            item.key
            for item in baseline.permit_types
            if item.fee_schedule_key in changed
        )
    )
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    priced_by_changed: set[str] = set()
    unpriceable: list[tuple[str, str, str]] = []
    changed_cases = 0
    priced = 0
    for case in cases:
        before = price_case(case, baseline)
        after = price_case(case, scenario.config)
        if not before.priceable or not after.priceable:
            unpriceable.append((case.case_ref, case.permit_type_key, before.reason or after.reason or ""))
            continue
        priced += 1
        row = totals[case.permit_type_key]
        row[0] += 1
        row[1] += before.total_cents or 0
        row[2] += after.total_cents or 0
        if before.fee_schedule_id in changed:
            priced_by_changed.add(case.permit_type_key)
        if before.total_cents != after.total_cents:
            changed_cases += 1
    by_type = tuple(
        TypeFeeTotals(key, values[0], values[1], values[2])
        for key, values in sorted(totals.items())
    )
    return FeeImpact(
        label=TOTAL_LABEL,
        note=TOTAL_NOTE,
        changed_schedule_ids=changed,
        types_sharing_changed_schedule=sharing,
        types_priced_by_changed_schedule=tuple(sorted(priced_by_changed)),
        priced_count=priced,
        baseline_total_cents=sum(row.baseline_cents for row in by_type),
        scenario_total_cents=sum(row.scenario_cents for row in by_type),
        by_type=by_type,
        unpriceable=tuple(sorted(unpriceable)),
        changed_case_count=changed_cases,
    )


__all__ = [
    "FEE_FIXED_KEY",
    "FEE_MULTIPLIER_KEY",
    "TOTAL_LABEL",
    "TOTAL_NOTE",
    "UNPRICEABLE_INVALID_SCHEDULE",
    "UNPRICEABLE_INVALID_VALUATION",
    "UNPRICEABLE_NO_SCHEDULE",
    "UNPRICEABLE_NO_VALUATION",
    "CaseFee",
    "FeeImpact",
    "TypeFeeTotals",
    "fee_impact",
    "price_case",
]
