"""AT17: repeatable fees.

A declared valuation of 50,000.00 is assessed at 150.00 USD.  The same case
reassessed at 70,000.00 is 170.00, the existing 150.00 is carried forward
once, the first version keeps its history, 20.00 is still due and the
issuance is blocked.
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
from acme_city.finance.schemas import (
    AllocationCommand,
    AssessmentCommand,
    ReassessmentCommand,
    ReconciliationCommand,
)
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


def _current_version(session, application_id: str) -> int:
    """Return the application version a decision is made against."""
    from acme_city.permits.service import PermitService

    return PermitService(session).load_application(application_id).version


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at17.db'}",
            "ACME_SECRET_KEY": "at17-repeatable-fees-secret-value",
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


def test_the_fee_is_repeatable_and_the_reassessment_carries_the_funds(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            finance_service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")

            first = finance_service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            assert first.assessed_total == "150.00"
            assert first.assessed_total_cents == 15000
            assert first.version == 1

            allocation = finance_service.allocate(
                AllocationCommand(
                    payment_id="payment_d01_settled",
                    assessment_id=first.assessment_id,
                    amount="150.00",
                    idempotency_key="alloc:at17:1",
                ),
                administrator,
            )
            assert allocation.amount_cents == 15000

            second = finance_service.reassess(
                ReassessmentCommand(
                    application_id="app_synth_001", valuation="70000.00"
                ),
                administrator,
            )
            assert second.assessed_total == "170.00"
            assert second.assessed_total_cents == 17000
            assert second.version == 2

            # The first version keeps its history and is no longer payable.
            stored_first = session.execute(
                select(finance.Assessment).where(
                    finance.Assessment.id == first.assessment_id
                )
            ).scalar_one()
            assert stored_first.status == "superseded"
            assert stored_first.assessed_total_cents == 15000

            # The paid funds are carried forward exactly once.
            allocations = session.execute(
                select(finance.Allocation).where(
                    finance.Allocation.assessment_id == second.assessment_id
                )
            ).scalars().all()
            assert len(allocations) == 1
            assert allocations[0].amount_cents == 15000
            assert allocations[0].status == "active"
            assert allocations[0].supersedes_allocation_id is not None
            released = session.execute(
                select(finance.Allocation).where(
                    finance.Allocation.id == allocations[0].supersedes_allocation_id
                )
            ).scalar_one()
            assert released.status == "released"
            assert released.amount_cents == 15000

            # Twenty dollars are still due.
            reconciliation = finance_service.reconcile(
                ReconciliationCommand(assessment_id=second.assessment_id), administrator
            )
            assert reconciliation.status == "partial"
            assert reconciliation.assessed_total == "170.00"
            assert reconciliation.settled_allocated == "150.00"
            assert reconciliation.balance == "20.00"
    finally:
        factory.dispose()


def test_the_issuance_is_blocked_while_twenty_dollars_are_due(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            permits = PermitService(session)
            finance_service = FinanceService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            administrator = context_for(session, "persona_city_administrator")

            evaluation = permits.evaluate("app_synth_001", reviewer)
            permits.decide(
                PermitDecisionCommand(
                    application_id="app_synth_001",
                    expected_application_version=_current_version(session, "app_synth_001"),
                    outcome="approved",
                    reason="Fictional demonstration approval.",
                    expected_evaluation_version=evaluation.version,
                ),
                reviewer,
            )
            first = finance_service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            finance_service.allocate(
                AllocationCommand(
                    payment_id="payment_d01_settled",
                    assessment_id=first.assessment_id,
                    amount="150.00",
                    idempotency_key="alloc:at17:block",
                ),
                administrator,
            )
            finance_service.reassess(
                ReassessmentCommand(
                    application_id="app_synth_001", valuation="70000.00"
                ),
                administrator,
            )

            application = permits.load_application("app_synth_001")
            decision = permits.current_decision("app_synth_001")
            assert decision is not None
            with pytest.raises(ValidationError) as raised:
                PermitIssuanceService(session).issue(
                    IssuePermitCommand(
                        application_id="app_synth_001",
                        decision_id=decision.id,
                        expected_application_version=application.version,
                        expected_decision_version=decision.version,
                        command_key="issue:at17:blocked",
                    ),
                    reviewer,
                )
            codes = {blocker["code"] for blocker in raised.value.details["blockers"]}
            assert "reconciliation_partial" in codes
            issued = session.execute(
                select(permit.Permit).where(
                    permit.Permit.application_id == "app_synth_001"
                )
            ).scalars().all()
            assert issued == []
    finally:
        factory.dispose()


def test_a_later_schedule_does_not_recalculate_a_historical_assessment(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            finance_service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            first = finance_service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            assert first.fee_schedule_version == "2026.1"
            assert first.assessed_total_cents == 15000

            # A later schedule version is published for the demonstration.
            session.add(
                finance.FeeScheduleVersion(
                    id="feesched_fee_commercial_demo_2026_3",
                    fee_schedule_id="fee_commercial_demo",
                    version_label="2026.3",
                    effective_from=datetime(2026, 1, 1, tzinfo=UTC),
                    effective_to=None,
                    currency="USD",
                    definition={
                        "fixed_review_charge_cents": 20000,
                        "valuation_multiplier": "0.002",
                        "version_basis": "initial_submitted_at",
                    },
                    status="published",
                    approver_actor_id="persona_city_administrator",
                    author_actor_id="persona_data_steward",
                )
            )
            session.flush()

            stored = session.execute(
                select(finance.Assessment).where(
                    finance.Assessment.id == first.assessment_id
                )
            ).scalar_one()
            assert stored.assessed_total_cents == 15000
            assert stored.fee_schedule_version_id == "feesched_fee_commercial_demo_2026_1"
    finally:
        factory.dispose()
