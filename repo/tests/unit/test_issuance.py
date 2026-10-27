"""Issuance tests: a separate, idempotent, simulated issuance.

Issuance checks the current application, evaluation, decision, links,
credentials, assessment and reconciliation in one transaction.  An identical
retry returns the original permit, number and artifact, and a reused command
key with other facts is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import ValidationError
from acme_city.core.results import ConflictResult
from acme_city.finance.schemas import AllocationCommand, AssessmentCommand
from acme_city.finance.service import FinanceService
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import finance, permit, registry
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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'issuance.db'}",
            "ACME_SECRET_KEY": "issuance-test-secret-value",
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


def prepare_the_chain(session) -> tuple[PermitService, FinanceService, ActorContext]:
    """Evaluate, approve, assess, allocate and reconcile the D01 case."""
    approve_links(session)
    permits = PermitService(session)
    finance_service = FinanceService(session)
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
            idempotency_key="alloc:test:issuance",
        ),
        administrator,
    )
    return permits, finance_service, reviewer


def issue_command(session, permits: PermitService, key: str = "issue:test:001") -> IssuePermitCommand:
    """Return an issuance command for the current state of the application."""
    application = permits.load_application("app_synth_001")
    decision = permits.current_decision("app_synth_001")
    assert decision is not None
    return IssuePermitCommand(
        application_id="app_synth_001",
        decision_id=decision.id,
        expected_application_version=application.version,
        expected_decision_version=decision.version,
        command_key=key,
    )


def test_an_issued_permit_carries_a_number_and_an_artifact(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            permits, _, reviewer = prepare_the_chain(session)
            service = PermitIssuanceService(session)
            result = service.issue(issue_command(session, permits), reviewer)
            assert not isinstance(result, ConflictResult)
            issued = result.value
            assert issued.permit_number.startswith("ACME-")
            assert issued.artifact_hash
            assert issued.fictional_demo is True
            assert issued.snapshot["decision"]["outcome"] == "approved"
            assert issued.snapshot["assessed_total_cents"] == 15000
            assert issued.snapshot["allocations"]

            stored = session.execute(
                select(permit.Permit).where(permit.Permit.id == issued.permit_id)
            ).scalar_one()
            assert stored.status == "issued"
            application = permits.load_application("app_synth_001")
            assert application.status == "issued"
    finally:
        factory.dispose()


def test_the_artifact_is_stable_and_fictional(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            permits, _, reviewer = prepare_the_chain(session)
            service = PermitIssuanceService(session)
            result = service.issue(issue_command(session, permits), reviewer)
            assert not isinstance(result, ConflictResult)
            artifact = service.render_artifact(result.value.permit_id)
            assert b"Simulated demonstration document" in artifact
            assert b"not an official city record" in artifact
            assert b"Westerville" not in artifact
            assert result.value.permit_number.encode("utf-8") in artifact
            # The same snapshot always renders the same bytes.
            assert service.render_artifact(result.value.permit_id) == artifact
    finally:
        factory.dispose()


def test_an_identical_retry_returns_the_original_permit(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            permits, _, reviewer = prepare_the_chain(session)
            service = PermitIssuanceService(session)
            command = issue_command(session, permits)
            first = service.issue(command, reviewer)
            second = service.issue(command, reviewer)
            assert not isinstance(first, ConflictResult)
            assert not isinstance(second, ConflictResult)
            assert second.value.permit_id == first.value.permit_id
            assert second.value.permit_number == first.value.permit_number
            assert second.value.artifact_hash == first.value.artifact_hash
            count = session.execute(
                select(permit.Permit).where(
                    permit.Permit.application_id == "app_synth_001"
                )
            ).scalars().all()
            assert len(count) == 1
    finally:
        factory.dispose()


def test_a_reused_command_key_with_other_facts_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            permits, _, reviewer = prepare_the_chain(session)
            service = PermitIssuanceService(session)
            command = issue_command(session, permits, key="issue:test:reuse")
            first = service.issue(command, reviewer)
            assert not isinstance(first, ConflictResult)
            application = permits.load_application("app_synth_001")
            decision = permits.current_decision("app_synth_001")
            assert decision is not None
            refused = service.issue(
                IssuePermitCommand(
                    application_id="app_synth_001",
                    decision_id=decision.id,
                    expected_application_version=application.version + 1,
                    expected_decision_version=decision.version,
                    command_key="issue:test:reuse",
                ),
                reviewer,
            )
            assert isinstance(refused, ConflictResult)
            assert refused.code == "issuance_key_reused"
    finally:
        factory.dispose()


def test_an_unpaid_case_may_not_be_issued(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            permits = PermitService(session)
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
            FinanceService(session).assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            service = PermitIssuanceService(session)
            with pytest.raises(ValidationError) as raised:
                service.issue(issue_command(session, permits), reviewer)
            codes = {blocker["code"] for blocker in raised.value.details["blockers"]}
            assert any(code.startswith("reconciliation_") for code in codes)
    finally:
        factory.dispose()


def test_an_unapproved_identity_may_not_be_issued(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            permits = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = permits.evaluate("app_synth_001", reviewer)
            with pytest.raises(ValidationError):
                permits.decide(
                    PermitDecisionCommand(
                        application_id="app_synth_001",
                        outcome="approved",
                        reason="Approval attempt.",
                        expected_evaluation_version=evaluation.version,
                    ),
                    reviewer,
                )
            assert permits.current_decision("app_synth_001") is None
    finally:
        factory.dispose()


def test_a_reviewer_approval_does_not_issue_a_permit(seeded: Settings) -> None:
    """Approval and issuance are separate actions."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            permits, _, reviewer = prepare_the_chain(session)
            issued = session.execute(
                select(permit.Permit).where(
                    permit.Permit.application_id == "app_synth_001"
                )
            ).scalars().all()
            assert issued == []
            application = permits.load_application("app_synth_001")
            assert application.status == "approved"
    finally:
        factory.dispose()
