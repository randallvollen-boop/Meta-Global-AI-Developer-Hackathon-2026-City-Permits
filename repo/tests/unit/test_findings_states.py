"""Findings: the two new types, the states and the way a rerun settles them.

A finding belongs to the application revision and the agent run that
produced it.  A rerun supersedes the findings it recorded again and
resolves the ones it did not; a resubmission supersedes the findings of
the earlier revisions.  The history is kept either way.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.agents.findings import (
    FINDING_TYPES,
    resolve_replaced_findings,
    supersede_findings_before,
)
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'findings.db'}",
            "ACME_SECRET_KEY": "findings-test-secret-value",
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


def finding(
    session,
    application_id: str,
    *,
    identifier: str,
    message: str,
    revision_number: int = 1,
    finding_type: str = "judgment",
) -> permit.ApplicationFinding:
    """Record one finding on a case."""
    row = permit.ApplicationFinding(
        id=identifier,
        correlation_id="corr_findings",
        application_id=application_id,
        finding_type=finding_type,
        message=message,
        rule="ACME Code §13-401",
        applicant_must="Confirm the case.",
        severity="review",
        state="current",
        revision_number=revision_number,
        version=1,
    )
    session.add(row)
    session.flush()
    return row


def test_the_two_new_finding_types_are_part_of_the_vocabulary() -> None:
    assert "wrong_type" in FINDING_TYPES
    assert "fee" in FINDING_TYPES
    # The seven types the application already had are still there.
    for existing in (
        "missing_field",
        "missing_document",
        "unreadable",
        "duplicate",
        "conflict",
        "low_confidence_extraction",
        "judgment",
    ):
        assert existing in FINDING_TYPES


def test_a_rerun_supersedes_the_findings_it_records_again(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            first = finding(
                session,
                "app_synth_001",
                identifier="finding_rerun_1",
                message="A duplicate.",
                finding_type="duplicate",
            )
            second = finding(
                session, "app_synth_001", identifier="finding_rerun_2", message="A conflict."
            )
            superseded, resolved = resolve_replaced_findings(
                session,
                "app_synth_001",
                revision_number=1,
                produced=[("duplicate", "A duplicate.")],
                at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
            )
            assert (superseded, resolved) == (1, 1)
            session.refresh(first)
            session.refresh(second)
            assert first.state == "superseded"
            assert first.superseded_at is not None
            assert second.state == "resolved"
            assert second.resolved_at is not None
    finally:
        factory.dispose()


def test_a_resubmission_supersedes_the_findings_of_the_earlier_revision(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            old = finding(
                session,
                "app_synth_001",
                identifier="finding_revision_1",
                message="A duplicate.",
                revision_number=1,
            )
            new = finding(
                session,
                "app_synth_001",
                identifier="finding_revision_2",
                message="A duplicate.",
                revision_number=2,
            )
            count = supersede_findings_before(
                session, "app_synth_001", revision_number=2
            )
            assert count == 1
            session.refresh(old)
            session.refresh(new)
            assert old.state == "superseded"
            assert new.state == "current"
    finally:
        factory.dispose()


def test_a_new_revision_supersedes_the_findings_of_the_earlier_one(seeded: Settings) -> None:
    """A resubmission supersedes the findings of the earlier revision."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = __import__(
                "acme_city.permits.service", fromlist=["PermitService"]
            ).PermitService(session)
            steward = context_for(session, "persona_data_steward")
            application = service.load_application("app_synth_001")
            finding(
                session,
                application.id,
                identifier="finding_resubmit_1",
                message="A duplicate.",
                revision_number=application.revision,
            )
            from acme_city.permits.schemas import ReviseApplicationCommand

            service.revise(
                ReviseApplicationCommand(
                    application_id=application.id,
                    facts={"valuation": "51000.00"},
                    reason="A fictional correction.",
                ),
                steward,
            )
            rows = session.execute(
                select(permit.ApplicationFinding).where(
                    permit.ApplicationFinding.id == "finding_resubmit_1"
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].state == "superseded"
    finally:
        factory.dispose()


def test_a_new_revision_makes_the_recommendation_stale(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = __import__(
                "acme_city.permits.service", fromlist=["PermitService"]
            ).PermitService(session)
            steward = context_for(session, "persona_data_steward")
            application = service.load_application("app_synth_001")
            recommendation = permit.Recommendation(
                id="recommendation_stale_1",
                application_id=application.id,
                proposed_outcome="approve",
                status="pending",
                version=1,
            )
            session.add(recommendation)
            session.flush()
            from acme_city.permits.schemas import ReviseApplicationCommand

            service.revise(
                ReviseApplicationCommand(
                    application_id=application.id,
                    facts={"valuation": "51000.00"},
                    reason="A fictional correction.",
                ),
                steward,
            )
            session.refresh(recommendation)
            assert recommendation.stale is True
            assert recommendation.status == "superseded"
    finally:
        factory.dispose()
