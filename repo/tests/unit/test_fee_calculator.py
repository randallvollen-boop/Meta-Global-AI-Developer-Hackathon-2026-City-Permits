"""Fee calculator tests: the exact arithmetic of the fictional schedule.

The same declared valuation always produces the same amount, the variable
component is rounded exactly once, and the lines multiply out to the total.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from acme_city.finance.calculator import (
    FIXED_FEE_CODE,
    MoneyError,
    VARIABLE_FEE_CODE,
    calculate_fee,
    format_cents,
    from_cents,
    to_cents,
    validate_currency,
)

#: The published fictional schedule of the demonstration.
DEFINITION = {
    "fixed_review_charge_cents": 10000,
    "valuation_multiplier": "0.001",
    "rounding": "ROUND_HALF_UP",
    "rounding_scope": "variable_component_once",
    "version_basis": "initial_submitted_at",
}


def test_fifty_thousand_is_one_hundred_and_fifty() -> None:
    assessment = calculate_fee(DEFINITION, 5000000, fee_schedule_id="fee_commercial_demo",
                               version_label="2026.1")
    assert assessment.total_cents == 15000
    assert format_cents(assessment.total_cents) == "150.00"
    assert [line.fee_code for line in assessment.lines] == [
        FIXED_FEE_CODE,
        VARIABLE_FEE_CODE,
    ]
    assert [line.amount_cents for line in assessment.lines] == [10000, 5000]


def test_seventy_thousand_is_one_hundred_and_seventy() -> None:
    assessment = calculate_fee(DEFINITION, 7000000, fee_schedule_id="fee_commercial_demo",
                               version_label="2026.1")
    assert assessment.total_cents == 17000
    assert format_cents(assessment.total_cents) == "170.00"


def test_the_variable_component_is_rounded_once() -> None:
    """One hundred and twenty three thousand four hundred fifty six cents."""
    assessment = calculate_fee(DEFINITION, 1234567)
    assert assessment.lines[1].amount_cents == 1235
    assert assessment.total_cents == 11235
    assert format_cents(assessment.total_cents) == "112.35"


def test_every_line_multiplies_out_to_its_amount() -> None:
    assessment = calculate_fee(DEFINITION, 12000000)
    for line in assessment.lines:
        quantity = Decimal(line.quantity)
        rate = Decimal(line.rate_cents) / Decimal(100)
        assert quantity * rate == from_cents(line.amount_cents)


def test_the_quantity_is_quoted_in_thousands_of_dollars() -> None:
    assessment = calculate_fee(DEFINITION, 12000000)
    assert assessment.lines[1].quantity == "120.000"
    assert assessment.lines[1].rate_cents == 100


def test_the_assessment_is_repeatable() -> None:
    first = calculate_fee(DEFINITION, 5000000)
    second = calculate_fee(DEFINITION, 5000000)
    assert first.total_cents == second.total_cents
    assert [line.to_dict() for line in first.lines] == [
        line.to_dict() for line in second.lines
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("150.00", 15000), ("150", 15000), (15000, 1500000), (Decimal("0.01"), 1)],
)
def test_amounts_convert_to_cents(value, expected) -> None:
    assert to_cents(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "1.234", None, True, float("nan")])
def test_unusable_amounts_are_refused(value) -> None:
    with pytest.raises(MoneyError):
        to_cents(value)


def test_the_currency_is_validated() -> None:
    assert validate_currency("usd") == "USD"
    assert validate_currency(None) == "USD"
    with pytest.raises(MoneyError):
        validate_currency("dollars")
    with pytest.raises(MoneyError):
        validate_currency("US")
