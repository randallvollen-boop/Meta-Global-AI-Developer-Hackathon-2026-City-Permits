"""Pure construction of the evaluated inputs of a submitted revision."""
# REQUIRES: PER-02
# The submitted facts are the inputs of an evaluation, in one place.

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from acme_city.finance.calculator import MoneyError, to_cents


def build_inputs(snapshot: Mapping[str, Any], *, strict: bool = True) -> dict[str, Any]:
    """Return the evaluated inputs of a submitted revision.

    The submitted facts are the inputs.  The parcel reference is presented
    under the name the catalogue uses, and the declared valuation is kept in
    cents beside its decimal form.  A declared valuation that is not an amount
    raises :class:`MoneyError` unless ``strict`` is false, in which case the
    raw value is left for the evaluator to report as an unusable input (the
    simulation uses this so one bad case never stops a run).
    """
    inputs = dict(snapshot)
    if "parcel_number" not in inputs:
        parcel = inputs.get("submitted_parcel")
        if parcel:
            inputs["parcel_number"] = parcel
    if "valuation_cents" not in inputs and inputs.get("valuation") is not None:
        try:
            inputs["valuation_cents"] = to_cents(inputs["valuation"])
        except MoneyError:
            if strict:
                raise
    return inputs


def missing_required_fields(
    required_fields: Iterable[str], inputs: Mapping[str, Any]
) -> list[str]:
    """Return the required fields that the inputs do not supply."""
    missing: list[str] = []
    for field in required_fields or []:
        value = inputs.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


NO_VALUATION = "no_valuation"
INVALID_VALUATION = "invalid_valuation"


def declared_valuation_cents(snapshot: Mapping[str, Any]) -> tuple[int | None, str | None]:
    """Return ``(cents, None)`` for the declared valuation, or ``(None, reason)``.

    The submitted revision may carry the valuation in cents already, or as a
    decimal amount.  The reason is ``no_valuation`` or ``invalid_valuation``.
    """
    if snapshot.get("valuation_cents") is not None:
        try:
            return int(snapshot["valuation_cents"]), None
        except (TypeError, ValueError):
            return None, INVALID_VALUATION
    if snapshot.get("valuation") is not None:
        try:
            return to_cents(snapshot["valuation"]), None
        except MoneyError:
            return None, INVALID_VALUATION
    return None, NO_VALUATION


__all__ = [
    "INVALID_VALUATION",
    "NO_VALUATION",
    "build_inputs",
    "declared_valuation_cents",
    "missing_required_fields",
]
