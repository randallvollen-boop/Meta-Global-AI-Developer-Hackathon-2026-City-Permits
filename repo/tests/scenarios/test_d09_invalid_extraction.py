"""D09: invalid inputs produce explicit review results.

A non-numeric value, a non-finite value, a blank conditional input and an
unsupported category each produce a review result.  None of them crashes and
none of them approves anything.
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
from acme_city.permits.service import PermitService


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'd09.db'}",
            "ACME_SECRET_KEY": "d09-invalid-extraction-secret-value",
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
def test_each_invalid_input_produces_a_review_result(
    seeded: Settings, application_id: str, rule_id: str, reason: str
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate(application_id, reviewer)

            results = {result.rule_id: result for result in evaluation.results}
            assert rule_id in results
            assert results[rule_id].status == "review"
            assert results[rule_id].reason == reason
            # Nothing was approved.
            assert evaluation.outcome != "pass"
            assert evaluation.outcome == "review"
    finally:
        factory.dispose()


def test_an_unknown_sign_type_is_not_treated_as_a_pass(seeded: Settings) -> None:
    """The unsupported category leaves the applicable area maximum undecided."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate("app_d09_unknown_sign", reviewer)
            results = {result.rule_id: result for result in evaluation.results}
            for rule_id in ("SG-1", "SG-2", "SG-3"):
                assert results[rule_id].status == "review"
                assert results[rule_id].reason == "unknown_category"
            # The sign area of 1000 sq ft was never compared against a limit.
            assert all(result.status != "fail" for result in evaluation.results)
    finally:
        factory.dispose()


def test_the_evaluation_never_crashes_and_records_the_review(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            for application_id in (
                "app_d09_setback",
                "app_d09_setback_nan",
                "app_d09_blank_location",
                "app_d09_unknown_sign",
            ):
                evaluation = service.evaluate(application_id, reviewer)
                assert evaluation.evaluation_id
                assert evaluation.results
                assert evaluation.outcome in {"review", "fail", "condition", "pass"}
    finally:
        factory.dispose()
