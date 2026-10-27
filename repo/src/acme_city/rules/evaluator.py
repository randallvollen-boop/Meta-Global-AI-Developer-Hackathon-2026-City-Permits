"""Deterministic evaluation of the selected rule versions.

The evaluator never decides anything.  It compares a validated input against
the selected rule version and reports one explicit outcome per applicable
rule.  A rule whose applicability, input or limit cannot be resolved produces
a ``review`` outcome; it never produces an implicit pass.

The four confirmed evaluator defects are handled here:

* a non-numeric value in a numeric field (``setback_ft='twenty'``),
* a non-finite value in a numeric field (``setback_ft='nan'``),
* a blank conditional input (``location=''``), and
* an unsupported category (``sign_type='billboard'``).
"""
# REQUIRES: PER-02, ING-02, REF-01
# A missing, malformed, non-finite or unsupported input produces a specific
# review outcome, and an applicability that cannot be decided is a review
# condition rather than an automatic approval.

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from acme_city.rules.schemas import RuleResult, RuleSetVersion, RuleVersionView

#: Sentinel for an input that the application did not supply at all.
MISSING: Any = object()

#: The vocabulary of ``on_violate`` mapped onto the result vocabulary.
ON_VIOLATE_STATUS: dict[str, str] = {
    "fail": "fail",
    "condition": "condition",
    "judgment": "review",
    "review": "review",
}


def is_blank(value: Any) -> bool:
    """Return whether ``value`` carries no usable content."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def coerce_decimal(value: Any) -> tuple[Decimal | None, str | None]:
    """Return ``value`` as an exact decimal, or a reason why it is not one.

    A boolean, a non-numeric string, a non-finite number and a negative
    magnitude are all refused.  The reason is a stable machine-readable code.
    """
    if value is MISSING or is_blank(value):
        return None, "missing_input"
    if isinstance(value, bool):
        return None, "non_numeric_input"
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, int):
        candidate = Decimal(value)
    elif isinstance(value, float):
        candidate = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            candidate = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None, "non_numeric_input"
    else:
        return None, "non_numeric_input"
    if not candidate.is_finite():
        return None, "nonfinite_input"
    if candidate < 0:
        return None, "negative_value"
    return candidate, None


def _normalise(value: Any) -> str:
    """Return a comparable text form of ``value``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, float):
        return format(Decimal(repr(value)).normalize(), "f")
    if isinstance(value, int):
        return str(value)
    return str(value).strip().lower()


def known_category_values(rule_set: RuleSetVersion) -> dict[str, set[str]]:
    """Return the categories each conditional field may take.

    The catalogue is the only place a category list comes from: the values a
    field may hold are exactly the values the published rules test for.
    """
    categories: dict[str, set[str]] = {}
    for rule in rule_set.rules:
        for field, value in (rule.condition or {}).items():
            if field == "field_above" or not isinstance(value, (str, int, float, bool)):
                continue
            categories.setdefault(field, set()).add(_normalise(value))
    return categories


def _condition_applicability(
    rule: RuleVersionView,
    inputs: Mapping[str, Any],
    categories: Mapping[str, set[str]],
) -> tuple[bool | None, str | None, str | None]:
    """Return ``(applicable, reason, detail)`` for a rule's condition.

    ``applicable`` is ``None`` when the condition cannot be decided.  A value
    outside the catalogue's known categories is unknown, not merely unequal:
    the rule may well apply to that variant of the fact.
    """
    condition = rule.condition or {}
    if not condition:
        return True, None, None

    unknown_reason: str | None = None
    unknown_detail: str | None = None
    excluded = False

    for field in sorted(key for key in condition if key != "field_above"):
        expected = condition[field]
        observed = inputs.get(field, MISSING)
        if observed is MISSING or is_blank(observed):
            if unknown_reason is None:
                unknown_reason = "missing_condition_input"
                unknown_detail = f"the conditional input {field!r} was not supplied"
            continue
        allowed = categories.get(field)
        if allowed is not None and _normalise(observed) not in allowed:
            if unknown_reason is None:
                unknown_reason = "unknown_category"
                unknown_detail = (
                    f"{field!r} is {observed!r}, which is not a category the catalogue defines"
                )
            continue
        if _normalise(observed) != _normalise(expected):
            excluded = True

    if unknown_reason == "unknown_category":
        return None, unknown_reason, unknown_detail
    if excluded:
        return False, None, None
    if unknown_reason is not None:
        return None, unknown_reason, unknown_detail

    above = condition.get("field_above")
    if isinstance(above, Mapping):
        field = str(above.get("field") or "")
        threshold, reason = coerce_decimal(above.get("value"))
        observed = inputs.get(field, MISSING)
        if threshold is None:
            return None, "invalid_condition_input", f"the condition threshold for {field!r} is invalid"
        if observed is MISSING or is_blank(observed):
            return None, "missing_condition_input", f"the conditional input {field!r} was not supplied"
        number, number_reason = coerce_decimal(observed)
        if number is None:
            return None, "invalid_condition_input", (
                f"the conditional input {field!r} is not a usable number ({number_reason})"
            )
        if number <= threshold:
            return False, None, None

    return True, None, None


def evaluate_rule(
    rule: RuleVersionView,
    inputs: Mapping[str, Any],
    categories: Mapping[str, set[str]],
) -> RuleResult | None:
    """Evaluate one rule against ``inputs``.

    Returns ``None`` when the rule does not apply, so that a rule which was
    never in scope never appears as a pass.
    """
    applicable, reason, detail = _condition_applicability(rule, inputs, categories)
    if applicable is False:
        return None
    if applicable is None:
        return RuleResult(
            rule_id=rule.rule_id,
            version_label=rule.version_label,
            citation=rule.citation,
            status="review",
            applicable=False,
            field_path=rule.field_path,
            observed_value=_observed(rule, inputs),
            limit_value=rule.limit_value,
            operator=rule.operator,
            message=rule.message,
            condition_note=rule.condition_note,
            reason=reason,
            detail=detail,
        )

    field_path = rule.field_path
    if not field_path:
        return RuleResult(
            rule_id=rule.rule_id,
            version_label=rule.version_label,
            citation=rule.citation,
            status="review",
            applicable=True,
            operator=rule.operator,
            message=rule.message,
            condition_note=rule.condition_note,
            reason="invalid_rule_definition",
            detail="the rule does not name the field it checks",
        )

    observed = inputs.get(field_path, MISSING)
    operator = (rule.operator or "").strip().lower()

    if operator == "required":
        # A presence check.  The fact has to have been supplied and must not
        # be blank; nothing is compared with a limit.
        limit = (rule.limit_value or "").strip()
        if observed is MISSING or is_blank(observed):
            return RuleResult(
                rule_id=rule.rule_id,
                version_label=rule.version_label,
                citation=rule.citation,
                status=ON_VIOLATE_STATUS.get(
                    (rule.on_violate or "").strip().lower(), "review"
                ),
                applicable=True,
                field_path=field_path,
                observed_value=None,
                limit_value=limit or None,
                operator=operator,
                message=rule.message,
                condition_note=rule.condition_note,
                reason="missing_input",
                detail=f"the value for {field_path!r} was not supplied",
                unit=rule.unit,
            )
        return RuleResult(
            rule_id=rule.rule_id,
            version_label=rule.version_label,
            citation=rule.citation,
            status="pass",
            applicable=True,
            field_path=field_path,
            observed_value=_observed(rule, inputs),
            limit_value=limit or None,
            operator=operator,
            message=rule.message,
            condition_note=rule.condition_note,
            reason="rule_satisfied",
            unit=rule.unit,
        )

    if operator == "equals":
        limit = (rule.limit_value or "").strip().lower()
        if observed is MISSING or is_blank(observed):
            return RuleResult(
                rule_id=rule.rule_id,
                version_label=rule.version_label,
                citation=rule.citation,
                status="review",
                applicable=True,
                field_path=field_path,
                observed_value=None,
                limit_value=rule.limit_value,
                operator=operator,
                message=rule.message,
                condition_note=rule.condition_note,
                reason="missing_input",
                detail=f"the value for {field_path!r} was not supplied",
            )
        if _normalise(observed) == limit:
            violated = True
        else:
            violated = False
    else:
        limit_number, limit_reason = coerce_decimal(rule.limit_value)
        if limit_number is None:
            return RuleResult(
                rule_id=rule.rule_id,
                version_label=rule.version_label,
                citation=rule.citation,
                status="review",
                applicable=True,
                field_path=field_path,
                observed_value=_observed(rule, inputs),
                limit_value=rule.limit_value,
                operator=operator,
                message=rule.message,
                condition_note=rule.condition_note,
                reason="invalid_limit",
                detail=f"the rule limit {rule.limit_value!r} is not a usable number ({limit_reason})",
            )
        number, number_reason = coerce_decimal(observed)
        if number is None:
            return RuleResult(
                rule_id=rule.rule_id,
                version_label=rule.version_label,
                citation=rule.citation,
                status="review",
                applicable=True,
                field_path=field_path,
                observed_value=_observed(rule, inputs),
                limit_value=rule.limit_value,
                operator=operator,
                message=rule.message,
                condition_note=rule.condition_note,
                reason=number_reason,
                detail=(
                    f"the value for {field_path!r} is not a usable number ({number_reason})"
                    if number_reason != "missing_input"
                    else f"the value for {field_path!r} was not supplied"
                ),
            )
        if operator == "min":
            violated = number < limit_number
        elif operator == "max":
            violated = number > limit_number
        else:
            return RuleResult(
                rule_id=rule.rule_id,
                version_label=rule.version_label,
                citation=rule.citation,
                status="review",
                applicable=True,
                field_path=field_path,
                observed_value=_observed(rule, inputs),
                limit_value=rule.limit_value,
                operator=operator,
                message=rule.message,
                condition_note=rule.condition_note,
                reason="invalid_rule_definition",
                detail=f"the rule operator {operator!r} is not supported",
            )

    if not violated:
        return RuleResult(
            rule_id=rule.rule_id,
            version_label=rule.version_label,
            citation=rule.citation,
            status="pass",
            applicable=True,
            field_path=field_path,
            observed_value=_observed(rule, inputs),
            limit_value=rule.limit_value,
            operator=operator,
            message=rule.message,
            condition_note=rule.condition_note,
            reason="rule_satisfied",
        )

    status = ON_VIOLATE_STATUS.get((rule.on_violate or "").strip().lower(), "review")
    return RuleResult(
        rule_id=rule.rule_id,
        version_label=rule.version_label,
        citation=rule.citation,
        status=status,
        applicable=True,
        field_path=field_path,
        observed_value=_observed(rule, inputs),
        limit_value=rule.limit_value,
        operator=operator,
        message=rule.message,
        condition_note=rule.condition_note,
        reason="rule_violated",
        detail=rule.message,
    )


def _observed(rule: RuleVersionView, inputs: Mapping[str, Any]) -> str | None:
    """Return the observed value of the rule's field as text."""
    if not rule.field_path:
        return None
    value = inputs.get(rule.field_path, MISSING)
    if value is MISSING:
        return None
    if isinstance(value, str):
        return value
    return _normalise(value)


def evaluate(
    inputs: Mapping[str, Any], rule_set: RuleSetVersion
) -> tuple[RuleResult, ...]:
    """Evaluate every selected rule against ``inputs``.

    The results are returned in the catalogue order of the rule set, so the
    same inputs and the same rule set always produce the same results.
    """
    categories = known_category_values(rule_set)
    results: list[RuleResult] = []
    for rule in rule_set.rules:
        outcome = evaluate_rule(rule, inputs, categories)
        if outcome is not None:
            results.append(outcome)
    return tuple(results)


def worst_status(statuses: Iterable[str]) -> str:
    """Return the worst of a collection of result statuses.

    The order of severity is ``fail``, ``review``, ``condition`` and ``pass``.
    An empty collection is ``review``: an evaluation that checked nothing
    never counts as an approval.
    """
    present = set(statuses)
    if not present:
        return "review"
    for status in ("fail", "review", "condition"):
        if status in present:
            return status
    return "pass"


def overall_status(results: Iterable[RuleResult]) -> str:
    """Return the worst outcome among ``results``."""
    return worst_status(result.status for result in results)


__all__ = [
    "MISSING",
    "ON_VIOLATE_STATUS",
    "coerce_decimal",
    "evaluate",
    "evaluate_rule",
    "is_blank",
    "known_category_values",
    "overall_status",
    "worst_status",
]
