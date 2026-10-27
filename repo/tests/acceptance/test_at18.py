"""AT18: payments and allocations.

A replayed payment and allocation create one receipt and no double use.  A
reversal keeps the event history, reopens the financial exception, blocks an
unissued permit and flags an issued permit for review.  The other financial
exceptions never satisfy the payment.
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
    PaymentEventCommand,
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


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at18.db'}",
            "ACME_SECRET_KEY": "at18-payments-and-allocations-secret",
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


def test_a_replayed_payment_and_allocation_use_the_receipt_once(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            finance_service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")

            assessment = finance_service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            command = AllocationCommand(
                payment_id="payment_d01_settled",
                assessment_id=assessment.assessment_id,
                amount="150.00",
                idempotency_key="alloc:at18:1",
            )
            first = finance_service.allocate(command, administrator)
            second = finance_service.allocate(command, administrator)
            assert first.allocation_id == second.allocation_id
            allocations = session.execute(
                select(finance.Allocation).where(
                    finance.Allocation.assessment_id == assessment.assessment_id
                )
            ).scalars().all()
            assert len(allocations) == 1

            # The receipt keeps one identity.
            receipts = session.execute(
                select(finance.Payment).where(
                    finance.Payment.source_transaction_id == "ERP-TXN-2026-04517"
                )
            ).scalars().all()
            assert len(receipts) == 1
    finally:
        factory.dispose()


def test_a_reversal_reopens_the_exception_and_blocks_an_unissued_permit(
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
                    idempotency_key="alloc:at18:reverse",
                ),
                administrator,
            )
            before = finance_service.reconcile(
                ReconciliationCommand(assessment_id=assessment.assessment_id), administrator
            )
            assert before.status == "exact"

            reversed_payment = finance_service.import_payment(
                PaymentEventCommand(
                    source_transaction_id="ERP-TXN-2026-04517",
                    source_event_id="ERP-EVT-2026-04517-3",
                    source_event_version="3",
                    event_type="reversed",
                    amount="150.00",
                    payer_account_id="facct_cedarline_legacy",
                    occurred_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
                ),
                administrator,
            )
            assert not isinstance(reversed_payment, finance.FinanceAccountLink)
            # The event history is retained.
            assert [item.event_type for item in reversed_payment.events] == [
                "received",
                "settled",
                "reversed",
            ]
            assert reversed_payment.settlement_status == "reversed"

            after = finance_service.reconcile(
                ReconciliationCommand(assessment_id=assessment.assessment_id), administrator
            )
            assert after.status == "reversed"
            assert after.exception == "reversed"

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
                        command_key="issue:at18:reversed",
                    ),
                    reviewer,
                )
            codes = {blocker["code"] for blocker in raised.value.details["blockers"]}
            assert "reconciliation_reversed" in codes
    finally:
        factory.dispose()


def test_a_reversal_flags_an_issued_permit_for_review(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            finance_service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            finance_service.import_payment(
                PaymentEventCommand(
                    source_transaction_id="ERP-TXN-2026-04100",
                    source_event_id="ERP-EVT-2026-04100-3",
                    source_event_version="3",
                    event_type="reversed",
                    amount="220.00",
                    payer_account_id=None,
                    party_id="party_marrow",
                    occurred_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
                ),
                administrator,
            )
            reviews = session.execute(
                select(permit.ImpactReview).where(
                    permit.ImpactReview.target_type == "permit",
                    permit.ImpactReview.target_id == "permit_d07",
                )
            ).scalars().all()
            assert len(reviews) == 1
            assert reviews[0].status == "open"
            # The issued permit was not cancelled.
            issued = session.execute(
                select(permit.Permit).where(permit.Permit.id == "permit_d07")
            ).scalar_one()
            assert issued.status == "issued"
    finally:
        factory.dispose()


def test_the_other_exceptions_never_satisfy_the_payment(seeded: Settings) -> None:
    """Partial, overpaid, unsettled, unmatched and currency conflicts."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            finance_service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            assessment = finance_service.assess(
                AssessmentCommand(application_id="app_d11"), administrator
            )

            # A partial payment of a linked payer leaves a balance.
            session.add(
                finance.FinanceAccountLink(
                    id="faclink_current",
                    account_id="facct_cedarline_current",
                    party_id="party_cedarline",
                    link_status="approved",
                    decided_by_actor_id="persona_data_steward",
                    decided_at=DECIDED_AT,
                )
            )
            session.flush()
            finance_service.import_payment(
                PaymentEventCommand(
                    source_transaction_id="ERP-TXN-2026-04518",
                    source_event_id="ERP-EVT-2026-04518-2",
                    event_type="settled",
                    amount="100.00",
                    payer_account_id="facct_cedarline_current",
                    occurred_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
                ),
                administrator,
            )
            finance_service.allocate(
                AllocationCommand(
                    payment_id="payment_d11_partial",
                    assessment_id=assessment.assessment_id,
                    amount="100.00",
                    idempotency_key="alloc:at18:partial",
                ),
                administrator,
            )
            partial = finance_service.reconcile(
                ReconciliationCommand(
                    assessment_id=assessment.assessment_id,
                    payment_ids=["payment_d11_partial"],
                ),
                administrator,
            )
            assert partial.status == "partial"
            assert partial.assessed_total == "150.00"
            assert partial.settled_allocated == "100.00"
            assert partial.balance == "50.00"

            # An unsettled receipt is never settled money.
            unsettled = finance_service.reconcile(
                ReconciliationCommand(
                    assessment_id=assessment.assessment_id,
                    payment_ids=["payment_d11_unsettled"],
                ),
                administrator,
            )
            assert unsettled.status == "unsettled"

            # A receipt in another currency is a currency conflict.
            currency = finance_service.reconcile(
                ReconciliationCommand(
                    assessment_id=assessment.assessment_id,
                    payment_ids=["payment_d11_other_currency"],
                ),
                administrator,
            )
            assert currency.status == "currency_conflict"

            # A receipt whose payer is not linked is unmatched.
            unmatched = finance_service.reconcile(
                ReconciliationCommand(
                    assessment_id=assessment.assessment_id,
                    payment_ids=["payment_d11_unmatched"],
                ),
                administrator,
            )
            assert unmatched.status == "unmatched"

            # A reversed receipt is not settled money either.
            reversed_receipt = finance_service.reconcile(
                ReconciliationCommand(
                    assessment_id=assessment.assessment_id,
                    payment_ids=["payment_d11_reversed"],
                ),
                administrator,
            )
            assert reversed_receipt.status == "reversed"
    finally:
        factory.dispose()
