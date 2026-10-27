"""Exact fee arithmetic.

Money is calculated with :class:`decimal.Decimal` and stored as integer cents.
The variable component of a fee is rounded exactly once, with
``ROUND_HALF_UP``; the fixed component needs no rounding at all.
"""
# REQUIRES: FIN-01, FIN-02
# A fee is calculated from approved inputs and the selected schedule with exact
# decimal arithmetic, and every line keeps its quantity, rate and amount.

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

#: The currency of the fictional demonstration.
DEFAULT_CURRENCY = "USD"

#: The number of minor units in one major unit.
MINOR_UNITS = 100

#: The rounding used for the variable component.
ROUNDING = ROUND_HALF_UP

#: The fee code of the fixed charge.
FIXED_FEE_CODE = "COM_REVIEW_FIXED"

#: The fee code of the valuation charge.
VARIABLE_FEE_CODE = "COM_REVIEW_VARIABLE"

#: The unit in which the valuation charge is quoted.
QUANTITY_UNIT = "thousands of declared valuation dollars"


class MoneyError(ValueError):
    """Raised when an amount or a currency cannot be used."""


def to_decimal(value: Any) -> Decimal:
    """Return ``value`` as an exact decimal.

    A float is read through its shortest representation so that the value
    the caller wrote is the value that is used.  A non-numeric value is
    refused.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise MoneyError("a boolean is not an amount")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise MoneyError("an amount must not be blank")
        try:
            return Decimal(text)
        except (InvalidOperation, ValueError) as exc:
            raise MoneyError(f"{value!r} is not an amount") from exc
    raise MoneyError(f"{value!r} is not an amount")


def to_cents(value: Any) -> int:
    """Return ``value`` as integer cents.

    The amount is converted exactly: a decimal with more than two minor
    digits is refused rather than silently rounded.
    """
    amount = to_decimal(value)
    if not amount.is_finite():
        raise MoneyError("an amount must be finite")
    scaled = amount * MINOR_UNITS
    if scaled != scaled.to_integral_value():
        raise MoneyError("an amount must not be finer than one cent")
    return int(scaled)


def from_cents(cents: int) -> Decimal:
    """Return integer cents as a decimal amount."""
    return (Decimal(int(cents)) / Decimal(MINOR_UNITS)).quantize(
        Decimal("0.01"), rounding=ROUNDING
    )


def format_cents(cents: int) -> str:
    """Return integer cents as a decimal string, for example ``150.00``."""
    return format(from_cents(cents), "f")


def validate_currency(currency: str | None) -> str:
    """Return the validated ISO currency code."""
    code = (currency or DEFAULT_CURRENCY).strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise MoneyError(f"{currency!r} is not an ISO currency code")
    return code


@dataclass(frozen=True)
class FeeLine:
    """One itemized line of an assessment."""

    fee_code: str
    description: str
    quantity: str
    rate_cents: int
    amount_cents: int
    currency: str = DEFAULT_CURRENCY
    rule_version_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the serialisable form of the line."""
        return {
            "fee_code": self.fee_code,
            "description": self.description,
            "quantity": self.quantity,
            "rate_cents": self.rate_cents,
            "amount_cents": self.amount_cents,
            "amount": format_cents(self.amount_cents),
            "currency": self.currency,
            "rule_version_id": self.rule_version_id,
        }


@dataclass(frozen=True)
class FeeAssessment:
    """The calculated lines and total of one assessment."""

    lines: tuple[FeeLine, ...]
    total_cents: int
    currency: str
    fee_schedule_id: str
    version_label: str
    valuation_cents: int

    def to_dict(self) -> dict[str, Any]:
        """Return the serialisable form of the assessment."""
        return {
            "lines": [line.to_dict() for line in self.lines],
            "total_cents": self.total_cents,
            "total": format_cents(self.total_cents),
            "currency": self.currency,
            "fee_schedule_id": self.fee_schedule_id,
            "version_label": self.version_label,
            "valuation_cents": self.valuation_cents,
        }


def calculate_fee(
    definition: Mapping[str, Any],
    valuation_cents: int,
    *,
    currency: str = DEFAULT_CURRENCY,
    fee_schedule_id: str = "",
    version_label: str = "",
) -> FeeAssessment:
    """Return the itemized assessment of a declared valuation.

    The schedule supplies a fixed charge and a multiplier on the declared
    valuation.  The variable component is rounded once, with
    ``ROUND_HALF_UP``, and the total is the exact sum of the lines.
    """
    code = validate_currency(currency)
    fixed_cents = int(definition.get("fixed_review_charge_cents", 0))
    multiplier = to_decimal(definition.get("valuation_multiplier", "0"))
    if multiplier < 0:
        raise MoneyError("a fee multiplier must not be negative")

    variable_cents = int(
        (to_decimal(valuation_cents) * multiplier).quantize(Decimal("1"), rounding=ROUNDING)
    )

    # The valuation is quoted in thousands of dollars so that the quantity
    # and the rate reproduce the amount exactly.
    quantity = (to_decimal(valuation_cents) / (Decimal(MINOR_UNITS) * Decimal("1000"))).quantize(
        Decimal("0.001"), rounding=ROUNDING
    )
    rate_cents = int(
        (multiplier * Decimal(MINOR_UNITS) * Decimal("1000")).quantize(
            Decimal("1"), rounding=ROUNDING
        )
    )

    lines = (
        FeeLine(
            fee_code=FIXED_FEE_CODE,
            description="Commercial plan review fixed charge",
            quantity="1",
            rate_cents=fixed_cents,
            amount_cents=fixed_cents,
            currency=code,
        ),
        FeeLine(
            fee_code=VARIABLE_FEE_CODE,
            description=f"Commercial plan review valuation charge per {QUANTITY_UNIT}",
            quantity=format(quantity, "f"),
            rate_cents=rate_cents,
            amount_cents=variable_cents,
            currency=code,
        ),
    )
    return FeeAssessment(
        lines=lines,
        total_cents=fixed_cents + variable_cents,
        currency=code,
        fee_schedule_id=fee_schedule_id,
        version_label=version_label,
        valuation_cents=valuation_cents,
    )


__all__ = [
    "DEFAULT_CURRENCY",
    "FIXED_FEE_CODE",
    "MINOR_UNITS",
    "QUANTITY_UNIT",
    "ROUNDING",
    "VARIABLE_FEE_CODE",
    "FeeAssessment",
    "FeeLine",
    "MoneyError",
    "calculate_fee",
    "format_cents",
    "from_cents",
    "to_cents",
    "to_decimal",
    "validate_currency",
]
