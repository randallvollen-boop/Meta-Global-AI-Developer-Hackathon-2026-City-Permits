"""Scenario changes and the in-memory scenario copy of the baseline.

A scenario is a name and an ordered list of typed changes.  Applying it to a
:class:`~acme_city.policy.config.PolicyConfig` produces a *copy*; the baseline
is never touched, and nothing is saved anywhere.

Supported change kinds:

* ``rule_threshold``   change a rule's limit and/or operator;
* ``rule_retirement``  retire a rule unconditionally;
* ``requirement``      add or remove a required field or document of a type;
* ``process_category`` move a type to another process category;
* ``discretionary``    make a type discretionary or non-discretionary;
* ``service_target``   change a type's service target (whole days);
* ``fee``              change a fixed charge or a valuation multiplier.

Everything else (a permit that is no longer required, removing plan review
for some cases only, retiring a rule for some cases only, any other fee
component) is **unsupported**: it is reported with an explicit
:class:`UnsupportedResponse` and the whole scenario is refused, never
partly applied.
"""
# REQUIRES: REF-01, PER-06
# A scenario is applied to a copy of the configuration; unsupported changes are
# refused explicitly and atomically.

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from acme_city.finance.calculator import MoneyError, to_decimal
from acme_city.kernel.selection import published_in_force
from acme_city.policy.config import (
    PROCESS_CATEGORIES,
    PolicyConfig,
    TypeConfig,
    digest,
)
from acme_city.rules.evaluator import coerce_decimal
from acme_city.rules.schemas import RULE_OPERATORS

KIND_RULE_THRESHOLD = "rule_threshold"
KIND_RULE_RETIREMENT = "rule_retirement"
KIND_REQUIREMENT = "requirement"
KIND_PROCESS_CATEGORY = "process_category"
KIND_DISCRETIONARY = "discretionary"
KIND_SERVICE_TARGET = "service_target"
KIND_FEE = "fee"

SUPPORTED_KINDS: tuple[str, ...] = (
    KIND_RULE_THRESHOLD,
    KIND_RULE_RETIREMENT,
    KIND_REQUIREMENT,
    KIND_PROCESS_CATEGORY,
    KIND_DISCRETIONARY,
    KIND_SERVICE_TARGET,
    KIND_FEE,
)

#: The kinds this release names and refuses.
UNSUPPORTED_NO_PERMIT = "no_permit_required"
UNSUPPORTED_PLAN_REVIEW = "conditional_plan_review_removal"
UNSUPPORTED_CONDITIONAL_RETIREMENT = "conditional_rule_retirement"
UNSUPPORTED_FEE_COMPONENT = "unsupported_fee_component"
UNSUPPORTED_UNKNOWN = "unknown_change_kind"

#: Fee definition keys a scenario may change.
FEE_FIXED_KEY = "fixed_review_charge_cents"
FEE_MULTIPLIER_KEY = "valuation_multiplier"

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

#: Names a "no permit required" change goes by when it is read from a request.
_NO_PERMIT_KINDS = frozenset({"no_permit_required", "no_permit", "exempt_type", "remove_permit"})
_PLAN_REVIEW_KINDS = frozenset(
    {"conditional_plan_review_removal", "remove_plan_review", "skip_plan_review"}
)


class ChangeError(ValueError):
    """Raised when a change request is malformed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RuleThresholdChange:
    """Change a rule's limit and/or operator."""

    rule_id: str
    limit_value: str | None = None
    operator: str | None = None
    kind: str = KIND_RULE_THRESHOLD


@dataclass(frozen=True)
class RuleRetirementChange:
    """Retire a rule for every case of its type, unconditionally."""

    rule_id: str
    kind: str = KIND_RULE_RETIREMENT


@dataclass(frozen=True)
class RequirementChange:
    """Add or remove one required field or document of a type."""

    permit_type_key: str
    item_kind: str  # "field" or "document"
    item: str
    action: str  # "add" or "remove"
    kind: str = KIND_REQUIREMENT


@dataclass(frozen=True)
class ProcessCategoryChange:
    """Move a type to another process category."""

    permit_type_key: str
    process_category: str
    kind: str = KIND_PROCESS_CATEGORY


@dataclass(frozen=True)
class DiscretionaryChange:
    """Make a type discretionary or non-discretionary (by right)."""

    permit_type_key: str
    discretionary: bool
    kind: str = KIND_DISCRETIONARY


@dataclass(frozen=True)
class ServiceTargetChange:
    """Change the service target of a type, in whole days."""

    permit_type_key: str
    service_target_days: int
    kind: str = KIND_SERVICE_TARGET


@dataclass(frozen=True)
class FeeChange:
    """Change a fixed charge and/or a valuation multiplier of a fee schedule."""

    fee_schedule_id: str
    fixed_review_charge_cents: int | None = None
    valuation_multiplier: str | None = None
    kind: str = KIND_FEE


@dataclass(frozen=True)
class UnsupportedChange:
    """A change request this release names and refuses."""

    requested_kind: str
    code: str
    detail: tuple[tuple[str, str], ...] = ()
    kind: str = "unsupported"


Change = (
    RuleThresholdChange
    | RuleRetirementChange
    | RequirementChange
    | ProcessCategoryChange
    | DiscretionaryChange
    | ServiceTargetChange
    | FeeChange
    | UnsupportedChange
)


@dataclass(frozen=True)
class Scenario:
    """A named, ordered set of proposed changes.  Held in memory only."""

    name: str
    changes: tuple[Change, ...]

    @property
    def scenario_hash(self) -> str:
        return digest({"name": self.name, "changes": [change_to_mapping(c) for c in self.changes]})


@dataclass(frozen=True)
class UnsupportedResponse:
    """The explicit answer to a change this release does not support."""

    change_index: int
    requested_kind: str
    code: str
    message: str
    supported: bool = False


@dataclass(frozen=True)
class ChangeIssue:
    """A supported kind that cannot be applied (unknown target, bad value)."""

    change_index: int
    code: str
    message: str


@dataclass(frozen=True)
class AppliedChange:
    """One change as it was applied: what it touched, before and after."""

    change_index: int
    change: Change
    target: str
    before: Mapping[str, Any]
    after: Mapping[str, Any]
    affected_type_keys: tuple[str, ...]
    citations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioConfigResult:
    """The outcome of applying a scenario to a baseline."""

    scenario: Scenario
    baseline_hash: str
    config: PolicyConfig | None
    applied: tuple[AppliedChange, ...]
    unsupported: tuple[UnsupportedResponse, ...]
    issues: tuple[ChangeIssue, ...]

    @property
    def supported(self) -> bool:
        """Whether every change was supported and applied."""
        return self.config is not None

    @property
    def scenario_config_hash(self) -> str | None:
        return None if self.config is None else self.config.config_hash


# ----------------------------------------------------------------- parsing


def change_to_mapping(change: Change) -> dict[str, Any]:
    """Return the plain mapping of a change (the inverse of :func:`parse_change`)."""
    if isinstance(change, UnsupportedChange):
        return {"kind": change.requested_kind, **dict(change.detail)}
    data = {key: value for key, value in change.__dict__.items()}
    return data


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ChangeError("missing_value", f"{key} is required")
    return value.strip()


def _name(raw: Mapping[str, Any], key: str) -> str:
    value = _text(raw, key)
    if not _NAME.match(value):
        raise ChangeError("invalid_name", f"{key} {value!r} is not a valid name")
    return value


def parse_change(raw: Mapping[str, Any]) -> Change:
    """Read one change request.

    An unsupported or unknown kind returns an :class:`UnsupportedChange`; a
    malformed supported kind raises :class:`ChangeError`.
    """
    kind = str(raw.get("kind") or "").strip().lower()
    detail = tuple(
        sorted((str(k), str(v)) for k, v in raw.items() if k != "kind")
    )
    if kind in _NO_PERMIT_KINDS:
        return UnsupportedChange(kind, UNSUPPORTED_NO_PERMIT, detail)
    if kind in _PLAN_REVIEW_KINDS:
        return UnsupportedChange(kind, UNSUPPORTED_PLAN_REVIEW, detail)
    if kind == KIND_RULE_RETIREMENT:
        if raw.get("when") or raw.get("condition"):
            return UnsupportedChange(kind, UNSUPPORTED_CONDITIONAL_RETIREMENT, detail)
        return RuleRetirementChange(rule_id=_text(raw, "rule_id"))
    if kind == KIND_RULE_THRESHOLD:
        limit = raw.get("limit_value")
        operator = raw.get("operator")
        if limit is None and operator is None:
            raise ChangeError("missing_value", "limit_value or operator is required")
        return RuleThresholdChange(
            rule_id=_text(raw, "rule_id"),
            limit_value=None if limit is None else str(limit).strip(),
            operator=None if operator is None else str(operator).strip().lower(),
        )
    if kind == KIND_REQUIREMENT:
        item_kind = _text(raw, "item_kind").lower()
        action = _text(raw, "action").lower()
        if item_kind not in ("field", "document"):
            raise ChangeError("invalid_value", "item_kind must be field or document")
        if action not in ("add", "remove"):
            raise ChangeError("invalid_value", "action must be add or remove")
        return RequirementChange(
            permit_type_key=_text(raw, "permit_type_key"),
            item_kind=item_kind,
            item=_name(raw, "item"),
            action=action,
        )
    if kind == KIND_PROCESS_CATEGORY:
        return ProcessCategoryChange(
            permit_type_key=_text(raw, "permit_type_key"),
            process_category=_text(raw, "process_category"),
        )
    if kind == KIND_DISCRETIONARY:
        value = raw.get("discretionary")
        if not isinstance(value, bool):
            raise ChangeError("invalid_value", "discretionary must be true or false")
        return DiscretionaryChange(_text(raw, "permit_type_key"), value)
    if kind == KIND_SERVICE_TARGET:
        days = raw.get("service_target_days")
        if isinstance(days, bool) or not isinstance(days, int):
            raise ChangeError("invalid_value", "service_target_days must be a whole number")
        return ServiceTargetChange(_text(raw, "permit_type_key"), days)
    if kind == KIND_FEE:
        extra = set(raw) - {"kind", "fee_schedule_id", FEE_FIXED_KEY, FEE_MULTIPLIER_KEY}
        if extra:
            return UnsupportedChange(kind, UNSUPPORTED_FEE_COMPONENT, detail)
        fixed = raw.get(FEE_FIXED_KEY)
        multiplier = raw.get(FEE_MULTIPLIER_KEY)
        if fixed is None and multiplier is None:
            raise ChangeError("missing_value", "a fixed charge or a multiplier is required")
        if fixed is not None and (isinstance(fixed, bool) or not isinstance(fixed, int)):
            raise ChangeError("invalid_value", f"{FEE_FIXED_KEY} must be whole cents")
        return FeeChange(
            fee_schedule_id=_text(raw, "fee_schedule_id"),
            fixed_review_charge_cents=fixed,
            valuation_multiplier=None if multiplier is None else str(multiplier).strip(),
        )
    return UnsupportedChange(kind or "(none)", UNSUPPORTED_UNKNOWN, detail)


def build_scenario(name: str, requests: Sequence[Mapping[str, Any]]) -> Scenario:
    """Read a scenario from change requests (raises :class:`ChangeError`)."""
    cleaned = name.strip() if isinstance(name, str) else ""
    if not cleaned:
        raise ChangeError("missing_value", "a scenario needs a name")
    if not requests:
        raise ChangeError("missing_value", "a scenario needs at least one change")
    return Scenario(name=cleaned, changes=tuple(parse_change(item) for item in requests))


def fence_height_limit_scenario(*, new_limit: str = "7") -> Scenario:
    """Return the headline demo scenario: the rear/side-yard fence limit 6 ft to 7 ft."""
    return Scenario(
        name="Rear and side yard fence limit 7 ft",
        changes=(RuleThresholdChange(rule_id="DF-2", limit_value=new_limit),),
    )


# ---------------------------------------------------------------- applying

_UNSUPPORTED_MESSAGES = {
    UNSUPPORTED_NO_PERMIT: (
        "Making a permit not required is not supported in this release; the "
        "scenario was not run."
    ),
    UNSUPPORTED_PLAN_REVIEW: (
        "Removing plan review for some cases only is not supported in this "
        "release; the scenario was not run."
    ),
    UNSUPPORTED_CONDITIONAL_RETIREMENT: (
        "Retiring a rule for some cases only is not supported in this release; "
        "retire it for every case or change its limit."
    ),
    UNSUPPORTED_FEE_COMPONENT: (
        "Only a fixed charge and a valuation multiplier can be changed; any other "
        "fee component is not supported."
    ),
    UNSUPPORTED_UNKNOWN: "This kind of change is not supported in this release.",
}


def apply_scenario(baseline: PolicyConfig, scenario: Scenario) -> ScenarioConfigResult:
    """Apply ``scenario`` to a copy of ``baseline``.

    The baseline is immutable and is never changed.  If any change is
    unsupported or cannot be applied, ``config`` is ``None`` and nothing is
    applied (all or nothing).
    """
    unsupported: list[UnsupportedResponse] = []
    issues: list[ChangeIssue] = []
    for index, change in enumerate(scenario.changes):
        if isinstance(change, UnsupportedChange):
            unsupported.append(
                UnsupportedResponse(
                    change_index=index,
                    requested_kind=change.requested_kind,
                    code=change.code,
                    message=_UNSUPPORTED_MESSAGES[change.code],
                )
            )
    if unsupported:
        return ScenarioConfigResult(
            scenario, baseline.config_hash, None, (), tuple(unsupported), ()
        )

    types = {item.key: item for item in baseline.permit_types}
    rules = list(baseline.rules)
    fees = list(baseline.fee_schedules)
    applied: list[AppliedChange] = []
    touched: set[tuple[str, str]] = set()

    def issue(index: int, code: str, message: str) -> None:
        issues.append(ChangeIssue(index, code, message))

    for index, change in enumerate(scenario.changes):
        if isinstance(change, (RuleThresholdChange, RuleRetirementChange)):
            targets = [
                position
                for position, rule in enumerate(rules)
                if rule.rule_id == change.rule_id
                and published_in_force(rule, baseline.analysis_at)
            ]
            if not targets:
                issue(index, "unknown_rule", f"rule {change.rule_id!r} is not in force")
                continue
            key = ("rule", change.rule_id)
            if key in touched:
                issue(index, "conflicting_change", f"rule {change.rule_id!r} is changed twice")
                continue
            touched.add(key)
            current = rules[targets[0]]
            type_key = current.permit_type_key or ""
            if isinstance(change, RuleRetirementChange):
                before = {"limit_value": current.limit_value, "operator": current.operator,
                          "in_force": True}
                for position in sorted(targets, reverse=True):
                    del rules[position]
                applied.append(
                    AppliedChange(
                        index, change, f"rule:{change.rule_id}", before, {"in_force": False},
                        (type_key,), (current.citation,),
                    )
                )
                continue
            new_operator = change.operator if change.operator is not None else current.operator
            new_limit = change.limit_value if change.limit_value is not None else current.limit_value
            problem = _threshold_problem(new_operator, new_limit)
            if problem:
                issue(index, "invalid_value", problem)
                continue
            before = {"limit_value": current.limit_value, "operator": current.operator}
            for position in targets:
                rules[position] = replace(
                    rules[position], limit_value=new_limit, operator=new_operator
                )
            applied.append(
                AppliedChange(
                    index, change, f"rule:{change.rule_id}", before,
                    {"limit_value": new_limit, "operator": new_operator},
                    (type_key,), (current.citation,),
                )
            )
            continue

        if isinstance(change, FeeChange):
            targets = [
                position
                for position, row in enumerate(fees)
                if row.fee_schedule_id == change.fee_schedule_id
                and published_in_force(row, baseline.analysis_at)
            ]
            if not targets:
                issue(index, "unknown_fee_schedule",
                      f"fee schedule {change.fee_schedule_id!r} is not in force")
                continue
            key = ("fee", change.fee_schedule_id)
            if key in touched:
                issue(index, "conflicting_change", "that fee schedule is changed twice")
                continue
            touched.add(key)
            problem = _fee_problem(change)
            if problem:
                issue(index, "invalid_value", problem)
                continue
            current = fees[targets[0]]
            before: dict[str, Any] = {}
            after: dict[str, Any] = {}
            for position in targets:
                definition = dict(fees[position].definition)
                if change.fixed_review_charge_cents is not None:
                    definition[FEE_FIXED_KEY] = change.fixed_review_charge_cents
                if change.valuation_multiplier is not None:
                    definition[FEE_MULTIPLIER_KEY] = change.valuation_multiplier
                if position == targets[0]:
                    before = {k: current.definition.get(k) for k in (FEE_FIXED_KEY, FEE_MULTIPLIER_KEY)}
                    after = {k: definition.get(k) for k in (FEE_FIXED_KEY, FEE_MULTIPLIER_KEY)}
                fees[position] = replace(fees[position], definition=definition)
            sharing = tuple(
                sorted(
                    item.key for item in types.values()
                    if item.fee_schedule_key == change.fee_schedule_id
                )
            )
            applied.append(
                AppliedChange(index, change, f"fee:{change.fee_schedule_id}", before, after, sharing)
            )
            continue

        # The remaining kinds change a permit type.
        type_key = change.permit_type_key  # type: ignore[union-attr]
        current_type = types.get(type_key)
        if current_type is None:
            issue(index, "unknown_permit_type", f"permit type {type_key!r} does not exist")
            continue
        target_key = (change.kind, type_key)
        if isinstance(change, RequirementChange):
            target_key = (change.kind, f"{type_key}:{change.item_kind}:{change.item}")
        if target_key in touched:
            issue(index, "conflicting_change", f"{type_key!r} is changed twice the same way")
            continue
        touched.add(target_key)
        updated, before, after, problem = _change_type(current_type, change)
        if problem:
            issue(index, "invalid_value", problem)
            continue
        types[type_key] = updated
        applied.append(
            AppliedChange(index, change, f"type:{type_key}", before, after, (type_key,))
        )

    if issues:
        return ScenarioConfigResult(
            scenario, baseline.config_hash, None, (), (), tuple(issues)
        )
    config = PolicyConfig(
        analysis_at=baseline.analysis_at,
        permit_types=tuple(types[item.key] for item in baseline.permit_types),
        rules=tuple(rules),
        fee_schedules=tuple(fees),
    )
    return ScenarioConfigResult(
        scenario, baseline.config_hash, config, tuple(applied), (), ()
    )


def _threshold_problem(operator: str | None, limit: str | None) -> str | None:
    if (operator or "") not in RULE_OPERATORS:
        return f"operator {operator!r} is not one of {', '.join(RULE_OPERATORS)}"
    if operator == "required":
        return None
    if operator == "equals":
        return None if (limit or "").strip() else "an equals rule needs a limit"
    number, reason = coerce_decimal(limit)
    if number is None:
        return f"limit {limit!r} is not a usable number ({reason})"
    return None


def _fee_problem(change: FeeChange) -> str | None:
    if change.fixed_review_charge_cents is not None and change.fixed_review_charge_cents < 0:
        return "a fixed charge must not be negative"
    if change.valuation_multiplier is not None:
        try:
            multiplier = to_decimal(change.valuation_multiplier)
        except MoneyError as exc:
            return str(exc)
        if not multiplier.is_finite() or multiplier < Decimal(0):
            return "a fee multiplier must be a finite number that is not negative"
    return None


def _change_type(
    current: TypeConfig, change: Change
) -> tuple[TypeConfig, dict[str, Any], dict[str, Any], str | None]:
    if isinstance(change, ProcessCategoryChange):
        if change.process_category not in PROCESS_CATEGORIES:
            return current, {}, {}, f"{change.process_category!r} is not a process category"
        return (
            replace(current, process_category=change.process_category),
            {"process_category": current.process_category},
            {"process_category": change.process_category},
            None,
        )
    if isinstance(change, DiscretionaryChange):
        return (
            replace(current, discretionary=change.discretionary),
            {"discretionary": current.discretionary},
            {"discretionary": change.discretionary},
            None,
        )
    if isinstance(change, ServiceTargetChange):
        if change.service_target_days < 1 or change.service_target_days > 365:
            return current, {}, {}, "a service target is 1 to 365 whole days"
        return (
            replace(current, service_target_days=change.service_target_days),
            {"service_target_days": current.service_target_days},
            {"service_target_days": change.service_target_days},
            None,
        )
    if isinstance(change, RequirementChange):
        attribute = "required_fields" if change.item_kind == "field" else "required_documents"
        existing: tuple[str, ...] = getattr(current, attribute)
        if change.action == "add":
            if change.item in existing:
                return current, {}, {}, f"{change.item!r} is already required"
            new = existing + (change.item,)
        else:
            if change.item not in existing:
                return current, {}, {}, f"{change.item!r} is not required"
            new = tuple(item for item in existing if item != change.item)
        return (
            replace(current, **{attribute: new}),
            {attribute: list(existing)},
            {attribute: list(new)},
            None,
        )
    return current, {}, {}, "unsupported change"


__all__ = [
    "KIND_DISCRETIONARY",
    "KIND_FEE",
    "KIND_PROCESS_CATEGORY",
    "KIND_REQUIREMENT",
    "KIND_RULE_RETIREMENT",
    "KIND_RULE_THRESHOLD",
    "KIND_SERVICE_TARGET",
    "SUPPORTED_KINDS",
    "UNSUPPORTED_CONDITIONAL_RETIREMENT",
    "UNSUPPORTED_FEE_COMPONENT",
    "UNSUPPORTED_NO_PERMIT",
    "UNSUPPORTED_PLAN_REVIEW",
    "UNSUPPORTED_UNKNOWN",
    "AppliedChange",
    "Change",
    "ChangeError",
    "ChangeIssue",
    "DiscretionaryChange",
    "FeeChange",
    "ProcessCategoryChange",
    "RequirementChange",
    "RuleRetirementChange",
    "RuleThresholdChange",
    "Scenario",
    "ScenarioConfigResult",
    "ServiceTargetChange",
    "UnsupportedChange",
    "UnsupportedResponse",
    "apply_scenario",
    "build_scenario",
    "change_to_mapping",
    "fence_height_limit_scenario",
    "parse_change",
]
