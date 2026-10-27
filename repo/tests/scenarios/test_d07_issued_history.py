"""D07: a change after issuance preserves the issued history.

The issued permit, its decision, its fee basis and its snapshot stay exactly
as they were.  The change opens a separate impact review, and the permit is
neither cancelled, revoked nor reissued silently.
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
from acme_city.persistence.models import finance, permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.impact import ChangeImpactCommand, ImpactService


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'd07.db'}",
            "ACME_SECRET_KEY": "d07-issued-history-secret-value",
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


def test_a_change_after_issuance_opens_an_impact_review(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            before_permit = session.execute(
                select(permit.Permit).where(permit.Permit.id == "permit_d07")
            ).scalar_one()
            before_decision = session.execute(
                select(permit.Decision).where(permit.Decision.id == "decision_d07")
            ).scalar_one()
            before_assessment = session.execute(
                select(finance.Assessment).where(
                    finance.Assessment.id == "assess_d07_v1"
                )
            ).scalar_one()
            before_snapshot = dict(before_permit.snapshot or {})

            steward = context_for(session, "persona_data_steward")
            summary = ImpactService(session).apply_change(
                ChangeImpactCommand(
                    kind="rule",
                    identifier="CT-2",
                    reason="A new version of the large tenant improvement rule was published.",
                ),
                steward,
            )
            assert summary.dependency_key == "rule:CT-2"
            affected = {case.application_id for case in summary.affected}
            assert "app_d07" in affected
            case = next(case for case in summary.affected if case.application_id == "app_d07")
            assert case.state == "issued"
            assert case.action == "impact_review"
            assert case.permit_id == "permit_d07"

            after_permit = session.execute(
                select(permit.Permit).where(permit.Permit.id == "permit_d07")
            ).scalar_one()
            after_decision = session.execute(
                select(permit.Decision).where(permit.Decision.id == "decision_d07")
            ).scalar_one()
            after_assessment = session.execute(
                select(finance.Assessment).where(
                    finance.Assessment.id == "assess_d07_v1"
                )
            ).scalar_one()

            # Nothing about the issued history moved.
            assert after_permit.status == "issued"
            assert after_permit.permit_number == before_permit.permit_number
            assert after_permit.artifact_hash == before_permit.artifact_hash
            assert dict(after_permit.snapshot or {}) == before_snapshot
            assert after_decision.outcome == before_decision.outcome
            assert after_decision.status == before_decision.status
            assert after_decision.stale == before_decision.stale
            assert after_assessment.assessed_total_cents == before_assessment.assessed_total_cents
            assert after_assessment.status == before_assessment.status

            review = session.execute(
                select(permit.ImpactReview).where(
                    permit.ImpactReview.id == case.impact_review_id
                )
            ).scalar_one()
            assert review.status == "open"
            assert review.assigned_actor_id == "persona_permit_reviewer"
            assert "CT-2" in review.reason
    finally:
        factory.dispose()


def test_the_same_change_does_not_open_a_second_review(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            service = ImpactService(session)
            command = ChangeImpactCommand(
                kind="rule",
                identifier="CT-2",
                reason="A new version of the large tenant improvement rule was published.",
            )
            first = service.apply_change(command, steward)
            second = service.apply_change(command, steward)
            assert first.affected[0].impact_review_id == second.affected[0].impact_review_id
            reviews = session.execute(
                select(permit.ImpactReview).where(
                    permit.ImpactReview.target_id == "permit_d07"
                )
            ).scalars().all()
            assert len(reviews) == 1
    finally:
        factory.dispose()
