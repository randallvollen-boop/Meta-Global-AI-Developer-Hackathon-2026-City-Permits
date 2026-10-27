"""AT12: invalid inputs.

``setback_ft='twenty'``, ``setback_ft='nan'``, a blank fence location and an
unknown ``sign_type`` with ``sign_area_sqft=1000`` each produce a validation
or review result.  None of them crashes and none of them approves anything.
Non-finite and negative values are refused as well.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.schemas import SubmitApplicationCommand
from acme_city.permits.service import PermitService


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at12.db'}",
            "ACME_SECRET_KEY": "at12-invalid-inputs-secret-value",
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


def context_for(session, actor_id: str) -> ActorContext:
    """Return the server-resolved context of a seeded persona."""
    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


@pytest.mark.parametrize(
    ("application_id", "rule_id", "reason"),
    [
        ("app_d09_setback", "DF-3", "non_numeric_input"),
        ("app_d09_setback_nan", "DF-3", "nonfinite_input"),
        ("app_d09_blank_location", "DF-1", "missing_condition_input"),
        ("app_d09_unknown_sign", "SG-1", "unknown_category"),
    ],
)
def test_each_invalid_input_yields_a_review_result(
    seeded: Settings, application_id: str, rule_id: str, reason: str
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate(application_id, reviewer)
            results = {result.rule_id: result for result in evaluation.results}
            assert results[rule_id].status == "review"
            assert results[rule_id].reason == reason
            assert evaluation.outcome != "pass"
    finally:
        factory.dispose()


def test_an_unknown_sign_type_with_a_large_area_is_not_approved(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate("app_d09_unknown_sign", reviewer)
            inputs = evaluation.inputs
            assert inputs["sign_type"] == "billboard"
            assert inputs["sign_area_sqft"] == 1000
            assert evaluation.outcome == "review"
            assert all(result.status != "pass" for result in evaluation.results[:3])
    finally:
        factory.dispose()


def test_a_negative_value_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            steward = context_for(session, "persona_data_steward")
            reviewer = context_for(session, "persona_permit_reviewer")
            submitted = service.submit(
                SubmitApplicationCommand(
                    permit_type_key="deck_fence",
                    applicant_party_id="party_applicant_1",
                    facts={
                        "project_description": "A fictional deck.",
                        "valuation": 9000.0,
                        "valuation_cents": 900000,
                        "structure_kind": "deck",
                        "setback_ft": -4,
                        "height_ft": 2.0,
                        "submitted_parcel": "ACME-P-1002",
                        "submitted_site_text": "12 Marrow Creek Road, ACME City",
                    },
                ),
                steward,
            )
            evaluation = service.evaluate(submitted.application_id, reviewer)
            results = {result.rule_id: result for result in evaluation.results}
            assert results["DF-3"].status == "review"
            assert results["DF-3"].reason == "negative_value"
    finally:
        factory.dispose()


def test_no_evaluation_crashes_on_any_seeded_application(seeded: Settings) -> None:
    """Every seeded case evaluates without an exception."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            for application_id in (
                "app_synth_001",
                "app_d02",
                "app_d03",
                "app_d04",
                "app_d05",
                "app_d06",
                "app_d07",
                "app_d08",
                "app_d09_setback",
                "app_d09_setback_nan",
                "app_d09_blank_location",
                "app_d09_unknown_sign",
                "app_d11",
            ):
                evaluation = service.evaluate(application_id, reviewer)
                assert evaluation.evaluation_id
                assert evaluation.outcome in {"pass", "condition", "fail", "review"}
    finally:
        factory.dispose()
