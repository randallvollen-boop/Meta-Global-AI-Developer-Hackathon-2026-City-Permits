"""AT10: issued history.

The same correction after issuance leaves the original permit, decision, fee
basis and issued snapshot exactly as they were.  A separate impact review
case shows the amendment route.
"""

from __future__ import annotations

from datetime import UTC, datetime
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

DECIDED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at10.db'}",
            "ACME_SECRET_KEY": "at10-issued-history-secret-value",
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


def test_the_issued_history_survives_a_later_correction(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            before = {
                "permit": session.execute(
                    select(permit.Permit).where(permit.Permit.id == "permit_d07")
                ).scalar_one(),
                "decision": session.execute(
                    select(permit.Decision).where(permit.Decision.id == "decision_d07")
                ).scalar_one(),
                "assessment": session.execute(
                    select(finance.Assessment).where(
                        finance.Assessment.id == "assess_d07_v1"
                    )
                ).scalar_one(),
                "allocation": session.execute(
                    select(finance.Allocation).where(
                        finance.Allocation.id == "alloc_d07_v1"
                    )
                ).scalar_one(),
            }
            snapshot = dict(before["permit"].snapshot or {})

            steward = context_for(session, "persona_data_steward")
            summary = ImpactService(session).apply_change(
                ChangeImpactCommand(
                    kind="rule",
                    identifier="CT-2",
                    reason="A new version of the large tenant improvement rule was published.",
                ),
                steward,
            )
            assert summary.affected
            case = summary.affected[0]
            assert case.state == "issued"

            after = {
                "permit": session.execute(
                    select(permit.Permit).where(permit.Permit.id == "permit_d07")
                ).scalar_one(),
                "decision": session.execute(
                    select(permit.Decision).where(permit.Decision.id == "decision_d07")
                ).scalar_one(),
                "assessment": session.execute(
                    select(finance.Assessment).where(
                        finance.Assessment.id == "assess_d07_v1"
                    )
                ).scalar_one(),
                "allocation": session.execute(
                    select(finance.Allocation).where(
                        finance.Allocation.id == "alloc_d07_v1"
                    )
                ).scalar_one(),
            }

            assert after["permit"].permit_number == before["permit"].permit_number
            assert after["permit"].issued_at == before["permit"].issued_at
            assert after["permit"].artifact_hash == before["permit"].artifact_hash
            assert after["permit"].status == "issued"
            assert dict(after["permit"].snapshot or {}) == snapshot

            assert after["decision"].outcome == before["decision"].outcome
            assert after["decision"].decided_at == before["decision"].decided_at
            assert after["decision"].decided_by_actor_id == before[
                "decision"
            ].decided_by_actor_id
            assert after["decision"].stale is False
            assert after["decision"].status == "current"

            assert after["assessment"].assessed_total_cents == before[
                "assessment"
            ].assessed_total_cents
            assert after["assessment"].status == "current"
            assert after["allocation"].status == "active"
            assert after["allocation"].amount_cents == before["allocation"].amount_cents
    finally:
        factory.dispose()


def test_a_separate_impact_review_shows_the_amendment_route(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            summary = ImpactService(session).apply_change(
                ChangeImpactCommand(
                    kind="rule",
                    identifier="CT-2",
                    reason="A new version of the large tenant improvement rule was published.",
                ),
                steward,
            )
            case = summary.affected[0]
            review = session.execute(
                select(permit.ImpactReview).where(
                    permit.ImpactReview.id == case.impact_review_id
                )
            ).scalar_one()
            assert review.target_type == "permit"
            assert review.target_id == "permit_d07"
            assert review.status == "open"
            assert review.assigned_actor_id == "persona_permit_reviewer"
            assert "amendment route" in review.reason
            # The permit itself was not cancelled, revoked or reissued.
            issued = session.execute(
                select(permit.Permit).where(permit.Permit.id == "permit_d07")
            ).scalar_one()
            assert issued.status == "issued"
            permits = session.execute(
                select(permit.Permit).where(permit.Permit.application_id == "app_d07")
            ).scalars().all()
            assert len(permits) == 1
    finally:
        factory.dispose()
