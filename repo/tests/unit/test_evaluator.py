"""Evaluator tests: the four confirmed defects and the result vocabulary.

An input that is missing, malformed, non-finite or unsupported produces an
explicit review outcome.  A rule whose applicability cannot be decided is a
review condition, never an automatic approval.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.rules.evaluator import coerce_decimal, evaluate, overall_status
from acme_city.rules.service import RuleCatalogService

BASIS = datetime(2026, 9, 8, 14, 30, tzinfo=UTC)


@pytest.fixture()
def catalog(seeded: Settings):
    """Return the catalogue service of a freshly reset database."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            yield RuleCatalogService(session)
    finally:
        factory.dispose()


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'evaluator.db'}",
            "ACME_SECRET_KEY": "evaluator-test-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                DemoEnvironment(
                    id="demo_environment_local",
                    environment_id=ENVIRONMENT_ID,
                    fictional_demo=True,
                    fixture_version=bundle.fixture_version,
                    label="local fictional demonstration",
                )
            )
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    finally:
        factory.dispose()
    return settings


def status_of(results, rule_id: str) -> str | None:
    """Return the status of one rule result."""
    for result in results:
        if result.rule_id == rule_id:
            return result.status
    return None


def test_a_non_numeric_value_is_a_review_result(catalog) -> None:
    rule_set = catalog.resolve("executable", "deck_fence", BASIS)
    results = evaluate({"structure_kind": "deck", "setback_ft": "twenty", "height_ft": 3.5}, rule_set)
    assert status_of(results, "DF-3") == "review"
    reason = next(result.reason for result in results if result.rule_id == "DF-3")
    assert reason == "non_numeric_input"
    assert overall_status(results) == "review"


def test_a_non_finite_value_is_a_review_result(catalog) -> None:
    rule_set = catalog.resolve("executable", "deck_fence", BASIS)
    results = evaluate({"structure_kind": "deck", "setback_ft": "nan", "height_ft": 3.5}, rule_set)
    assert status_of(results, "DF-3") == "review"
    reason = next(result.reason for result in results if result.rule_id == "DF-3")
    assert reason == "nonfinite_input"


def test_a_negative_value_is_refused(catalog) -> None:
    rule_set = catalog.resolve("executable", "deck_fence", BASIS)
    results = evaluate({"structure_kind": "deck", "setback_ft": -4, "height_ft": 3.5}, rule_set)
    assert status_of(results, "DF-3") == "review"
    reason = next(result.reason for result in results if result.rule_id == "DF-3")
    assert reason == "negative_value"


def test_a_blank_conditional_input_is_a_review_result(catalog) -> None:
    """A blank fence location leaves the applicable maximum undecided."""
    rule_set = catalog.resolve("executable", "deck_fence", BASIS)
    results = evaluate({"structure_kind": "fence", "location": "", "height_ft": 4}, rule_set)
    assert status_of(results, "DF-1") == "review"
    assert status_of(results, "DF-2") == "review"
    reason = next(result.reason for result in results if result.rule_id == "DF-1")
    assert reason == "missing_condition_input"
    assert overall_status(results) == "review"


def test_an_unsupported_category_is_a_review_result(catalog) -> None:
    """An unknown sign type leaves the applicable area maximum undecided."""
    rule_set = catalog.resolve("executable", "sign", BASIS)
    results = evaluate(
        {"sign_type": "billboard", "sign_area_sqft": 1000, "illuminated": "no"}, rule_set
    )
    for rule_id in ("SG-1", "SG-2", "SG-3"):
        assert status_of(results, rule_id) == "review"
        reason = next(result.reason for result in results if result.rule_id == rule_id)
        assert reason == "unknown_category"
    assert overall_status(results) == "review"


def test_a_rule_that_does_not_apply_produces_no_result(catalog) -> None:
    rule_set = catalog.resolve("executable", "deck_fence", BASIS)
    results = evaluate({"structure_kind": "deck", "setback_ft": 10, "height_ft": 2.0}, rule_set)
    assert status_of(results, "DF-1") is None
    assert status_of(results, "DF-2") is None
    assert status_of(results, "DF-3") == "pass"
    assert status_of(results, "DF-4") == "pass"
    assert overall_status(results) == "pass"


def test_a_violated_rule_reports_its_declared_outcome(catalog) -> None:
    rule_set = catalog.resolve("executable", "deck_fence", BASIS)
    results = evaluate({"structure_kind": "deck", "setback_ft": 10, "height_ft": 3.5}, rule_set)
    assert status_of(results, "DF-4") == "condition"
    assert overall_status(results) == "condition"

    rule_set = catalog.resolve("executable", "deck_fence", BASIS)
    results = evaluate({"structure_kind": "deck", "setback_ft": 4, "height_ft": 2.0}, rule_set)
    assert status_of(results, "DF-3") == "fail"
    assert overall_status(results) == "fail"


def test_a_judgment_rule_is_a_review_outcome(catalog) -> None:
    """A rule that asks for human judgment never becomes an automatic pass."""
    rule_set = catalog.resolve("executable", "com_ti", BASIS)
    results = evaluate(
        {"valuation_cents": 5000000, "valuation": 50000.0, "occupancy_load": 42}, rule_set
    )
    assert status_of(results, "CT-1") == "pass"
    assert status_of(results, "CT-2") == "pass"

    results = evaluate(
        {"valuation_cents": 30000000, "valuation": 300000.0, "occupancy_load": 42}, rule_set
    )
    assert status_of(results, "CT-2") == "review"
    assert overall_status(results) == "review"


def test_a_missing_input_is_never_an_implicit_pass(catalog) -> None:
    rule_set = catalog.resolve("executable", "com_ti", BASIS)
    results = evaluate({"occupancy_load": 42}, rule_set)
    assert status_of(results, "CT-2") == "review"
    reason = next(result.reason for result in results if result.rule_id == "CT-2")
    assert reason == "missing_input"
    assert overall_status(results) == "review"


def test_a_required_rule_passes_when_the_fact_is_there(catalog) -> None:
    """A presence check passes when the field was supplied and is not blank."""
    rule_set = catalog.resolve("executable", "hvac", BASIS)
    results = evaluate(
        {"parcel_number": "ACME-P-1001", "contractor_license": "ACME-LIC-1042"}, rule_set
    )
    assert status_of(results, "HV-1") == "pass"
    assert overall_status(results) == "pass"


def test_a_required_rule_fails_when_the_fact_is_absent(catalog) -> None:
    """A presence check fails when the field was never supplied."""
    rule_set = catalog.resolve("executable", "hvac", BASIS)
    results = evaluate({"parcel_number": "ACME-P-1001"}, rule_set)
    assert status_of(results, "HV-1") == "fail"
    assert overall_status(results) == "fail"


def test_a_required_rule_fails_when_the_fact_is_blank(catalog) -> None:
    """A blank value is not a supplied fact."""
    rule_set = catalog.resolve("executable", "hvac", BASIS)
    results = evaluate(
        {"parcel_number": "ACME-P-1001", "contractor_license": "   "}, rule_set
    )
    assert status_of(results, "HV-1") == "fail"


def test_a_required_rule_may_carry_a_condition(catalog) -> None:
    """A presence check may carry a condition instead of a failure."""
    rule_set = catalog.resolve("executable", "change_occupancy", BASIS)
    results = evaluate(
        {
            "parcel_number": "ACME-P-1001",
            "prior_use": "Small retail unit",
            "proposed_use": "Restaurant",
        },
        rule_set,
    )
    assert status_of(results, "CO-1") == "pass"
    assert status_of(results, "CO-2") == "pass"
    assert status_of(results, "CO-3") == "condition"
    assert overall_status(results) == "condition"


def test_the_shed_area_rule_has_three_bands(catalog) -> None:
    """At most 200 sq ft passes, 200 to 600 is a condition, over 600 fails."""
    rule_set = catalog.resolve("executable", "shed", BASIS)

    results = evaluate({"parcel_number": "ACME-P-1001", "shed_area_sqft": 150}, rule_set)
    assert status_of(results, "SH-1") == "pass"
    assert status_of(results, "SH-2") == "pass"
    assert overall_status(results) == "pass"

    results = evaluate({"parcel_number": "ACME-P-1001", "shed_area_sqft": 400}, rule_set)
    assert status_of(results, "SH-1") == "pass"
    assert status_of(results, "SH-2") == "condition"
    assert overall_status(results) == "condition"

    results = evaluate({"parcel_number": "ACME-P-1001", "shed_area_sqft": 700}, rule_set)
    assert status_of(results, "SH-1") == "fail"
    assert overall_status(results) == "fail"


def test_the_container_duration_rule_conditions_beyond_thirty_days(catalog) -> None:
    """At most 30 days passes; more is a condition."""
    rule_set = catalog.resolve("executable", "pod", BASIS)
    results = evaluate({"parcel_number": "ACME-P-1001", "pod_duration_days": 30}, rule_set)
    assert status_of(results, "PD-1") == "pass"
    results = evaluate({"parcel_number": "ACME-P-1001", "pod_duration_days": 45}, rule_set)
    assert status_of(results, "PD-1") == "condition"


def test_the_licensed_contractor_rules_fail_without_a_contractor(catalog) -> None:
    """The HVAC, water-heater and electric rules all need a contractor."""
    for permit_type, rule_id in (
        ("hvac", "HV-1"),
        ("water_heater", "WH-1"),
        ("residential_electric", "RE-1"),
    ):
        rule_set = catalog.resolve("executable", permit_type, BASIS)
        results = evaluate({"parcel_number": "ACME-P-1001"}, rule_set)
        assert status_of(results, rule_id) == "fail", permit_type
        results = evaluate(
            {"parcel_number": "ACME-P-1001", "contractor_license": "ACME-LIC-1042"}, rule_set
        )
        assert status_of(results, rule_id) == "pass", permit_type


def test_the_fire_alarm_rule_requires_construction_plans(catalog) -> None:
    """A commercial fire alarm needs the construction plans."""
    rule_set = catalog.resolve("executable", "fire_alarm", BASIS)
    results = evaluate(
        {"parcel_number": "ACME-P-1001", "construction_plans_received": "no"}, rule_set
    )
    assert status_of(results, "FA-1") == "fail"
    results = evaluate(
        {"parcel_number": "ACME-P-1001", "construction_plans_received": "yes"}, rule_set
    )
    assert status_of(results, "FA-1") == "pass"


def test_the_patio_rule_conditions_without_the_acknowledgement(catalog) -> None:
    """The patio rule conditions when the setback is not acknowledged."""
    rule_set = catalog.resolve("executable", "patio", BASIS)
    results = evaluate(
        {"parcel_number": "ACME-P-1001", "setback_acknowledged": "no"}, rule_set
    )
    assert status_of(results, "PA-1") == "condition"
    results = evaluate(
        {"parcel_number": "ACME-P-1001", "setback_acknowledged": "yes"}, rule_set
    )
    assert status_of(results, "PA-1") == "pass"


def test_a_discretionary_type_carries_no_rule(catalog) -> None:
    """A discretionary type has no published rule, so nothing is evaluated."""
    for permit_type in (
        "site_plan_review",
        "rezoning",
        "zoning_variance",
        "certificate_appropriateness",
    ):
        rule_set = catalog.resolve("executable", permit_type, BASIS)
        assert list(rule_set.rules) == [], permit_type


def test_evaluation_is_deterministic(catalog) -> None:
    rule_set = catalog.resolve("executable", "deck_fence", BASIS)
    inputs = {"structure_kind": "deck", "setback_ft": 10, "height_ft": 3.5}
    first = evaluate(inputs, rule_set)
    second = evaluate(inputs, rule_set)
    assert [result.model_dump() for result in first] == [result.model_dump() for result in second]


def test_an_empty_result_set_is_never_an_approval(catalog) -> None:
    rule_set = catalog.resolve("executable", "com_ti", BASIS)
    assert overall_status(evaluate({}, rule_set)) == "review"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12, "12"),
        ("12.5", "12.5"),
        (None, None),
        ("", None),
        ("twenty", None),
        (float("nan"), None),
        (float("inf"), None),
        (-1, None),
        (True, None),
    ],
)
def test_numeric_coercion_refuses_unusable_values(value, expected) -> None:
    number, reason = coerce_decimal(value)
    if expected is None:
        assert number is None
        assert reason
    else:
        assert number is not None
        assert reason is None
