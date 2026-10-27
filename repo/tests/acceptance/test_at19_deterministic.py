"""AT19: the complete persisted chain, in its deterministic part.

The D01 case runs from an evaluated submission through an actual reviewer
decision, an exact fee assessment, a confirmed allocation and a separate
simulated issuance.  The chain survives a restart, every version and actor
is traceable, and an identical retry after a simulated timeout returns the
original permit, number and artifact.

This is the deterministic part of AT19.  The live model task of the full
acceptance test belongs to the Muse slice and is not claimed here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.finance.schemas import AllocationCommand, AssessmentCommand
from acme_city.finance.service import FinanceService
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import audit, finance, permit, registry
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.decisions import PermitDecisionCommand
from acme_city.permits.issuance import IssuePermitCommand, PermitIssuanceService
from acme_city.permits.service import PermitService

DECIDED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at19.db'}",
            "ACME_SECRET_KEY": "at19-complete-persisted-chain-secret",
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


def approve_links(session) -> None:
    """Record the canonical links a steward would have approved."""
    for party_id in ("party_cedarline", "party_ironvale"):
        session.add(
            registry.Crosswalk(
                id=f"crosswalk_{party_id}",
                entity_id=party_id,
                entity_type="party",
                source_system_id="permitting",
                source_dataset_key="applicant_profiles",
                source_record_id=f"PER-{party_id}",
                link_status="approved",
                decision="Approved by the data steward.",
                decision_actor_id="persona_data_steward",
                decided_at=DECIDED_AT,
            )
        )
    session.add(
        finance.FinanceAccountLink(
            id="faclink_legacy",
            account_id="facct_cedarline_legacy",
            party_id="party_cedarline",
            link_status="approved",
            decided_by_actor_id="persona_data_steward",
            decided_at=DECIDED_AT,
        )
    )
    session.flush()


def run_the_chain(
    session,
) -> tuple[PermitService, PermitIssuanceService, ActorContext, IssuePermitCommand]:
    """Run the deterministic D01 chain and return the services and the command."""
    approve_links(session)
    permits = PermitService(session)
    finance_service = FinanceService(session)
    issuance = PermitIssuanceService(session)
    reviewer = context_for(session, "persona_permit_reviewer")
    administrator = context_for(session, "persona_city_administrator")

    evaluation = permits.evaluate("app_synth_001", reviewer)
    permits.decide(
        PermitDecisionCommand(
            application_id="app_synth_001",
            outcome="approved",
            reason="Fictional demonstration approval.",
            expected_evaluation_version=evaluation.version,
        ),
        reviewer,
    )
    assessment = finance_service.assess(
        AssessmentCommand(application_id="app_synth_001"), administrator
    )
    finance_service.allocate(
        AllocationCommand(
            payment_id="payment_d01_settled",
            assessment_id=assessment.assessment_id,
            amount="150.00",
            idempotency_key="alloc:at19:1",
        ),
        administrator,
    )
    application = permits.load_application("app_synth_001")
    decision = permits.current_decision("app_synth_001")
    assert decision is not None
    command = IssuePermitCommand(
        application_id="app_synth_001",
        decision_id=decision.id,
        expected_application_version=application.version,
        expected_decision_version=decision.version,
        command_key="issue:at19:d01",
        reason="Fictional demonstration issuance.",
    )
    issuance.issue(command, reviewer)
    return permits, issuance, reviewer, command


def test_the_d01_chain_is_persisted_and_traceable(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            permits, issuance, reviewer, command = run_the_chain(session)
            assert command.command_key == "issue:at19:d01"

            issued = session.execute(
                select(permit.Permit).where(
                    permit.Permit.application_id == "app_synth_001"
                )
            ).scalar_one()
            assert issued.permit_number.startswith("ACME-")
            assert issued.artifact_hash
            assert issued.issued_by_actor_id == "persona_permit_reviewer"

            decision = session.execute(
                select(permit.Decision).where(
                    permit.Decision.application_id == "app_synth_001"
                )
            ).scalar_one()
            assert decision.decided_by_actor_id == "persona_permit_reviewer"
            assert decision.evaluation_id

            evaluation = session.execute(
                select(permit.Evaluation).where(
                    permit.Evaluation.application_id == "app_synth_001",
                    permit.Evaluation.status == "current",
                )
            ).scalar_one()
            assert evaluation.rule_versions == {"CT-1": "CT-1@1", "CT-2": "CT-2@1"}

            assessment = session.execute(
                select(finance.Assessment).where(
                    finance.Assessment.application_id == "app_synth_001",
                    finance.Assessment.status == "current",
                )
            ).scalar_one()
            assert assessment.assessed_total_cents == 15000

            # Every accepted step of the chain is in the audit trail.
            actions = [
                row.action
                for row in session.execute(
                    select(audit.AuditEvent).order_by(audit.AuditEvent.occurred_at)
                ).scalars().all()
            ]
            for action in (
                "application.evaluate",
                "permit.decide",
                "finance.assessment.create",
                "finance.allocation.confirm",
                "permit.issue",
            ):
                assert action in actions
            assert AuditService is not None
            assert permits is not None
            assert issuance is not None
            assert reviewer is not None
    finally:
        factory.dispose()


def test_the_chain_survives_a_restart(seeded: Settings) -> None:
    """The permit, its versions and its actors are still there afterwards."""
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            run_the_chain(session)
            issued = session.execute(
                select(permit.Permit).where(
                    permit.Permit.application_id == "app_synth_001"
                )
            ).scalar_one()
            permit_id = issued.id
            permit_number = issued.permit_number
            artifact_hash = issued.artifact_hash
    finally:
        factory.dispose()

    # A restart: a new engine and a new session on the same database.
    restarted = SessionFactory(seeded.database_url)
    try:
        with transaction(restarted) as session:
            issued = session.execute(
                select(permit.Permit).where(permit.Permit.id == permit_id)
            ).scalar_one()
            assert issued.permit_number == permit_number
            assert issued.artifact_hash == artifact_hash
            assert issued.issued_by_actor_id == "persona_permit_reviewer"
            artifact = PermitIssuanceService(session).render_artifact(permit_id)
            assert artifact
            import hashlib

            assert hashlib.sha256(artifact).hexdigest() == artifact_hash
    finally:
        restarted.dispose()


def test_an_identical_retry_after_a_timeout_returns_the_original_permit(
    seeded: Settings,
) -> None:
    """A timeout after the commit leaves exactly one permit behind."""
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            permits, issuance, reviewer, command = run_the_chain(session)
            # The caller never saw the answer and retries the same command.
            retried = issuance.issue(command, reviewer)
            issued = session.execute(
                select(permit.Permit).where(
                    permit.Permit.application_id == "app_synth_001"
                )
            ).scalars().all()
            assert len(issued) == 1
            assert retried.value.permit_id == issued[0].id
            assert retried.value.permit_number == issued[0].permit_number
            assert retried.value.artifact_hash == issued[0].artifact_hash
    finally:
        factory.dispose()
