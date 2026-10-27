"""Allocation tests: governed allocation of settled funds.

Finance confirms an allocation against an immutable assessment version.  A
duplicate is harmless, a reused key with other facts is a conflict, and an
allocation beyond the available settled funds, against an unsettled or
reversed receipt, in another currency or for an unlinked payer is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError, ValidationError
from acme_city.core.results import ConflictResult
from acme_city.finance.schemas import AllocationCommand, AssessmentCommand, PaymentEventCommand
from acme_city.finance.service import FinanceService
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import finance
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

OCCURRED = datetime(2026, 9, 14, 15, 20, tzinfo=UTC)


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'allocations.db'}",
            "ACME_SECRET_KEY": "allocations-test-secret-value",
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


def link_the_payer(session) -> None:
    """Record the approved link of the payer account."""
    session.add(
        finance.FinanceAccountLink(
            id="faclink_legacy",
            account_id="facct_cedarline_legacy",
            party_id="party_cedarline",
            link_status="approved",
            decided_by_actor_id="persona_data_steward",
            decided_at=OCCURRED,
        )
    )
    session.flush()


def settle_a_payment(
    session,
    service: FinanceService,
    administrator: ActorContext,
    *,
    transaction_id: str = "ERP-TXN-2026-90010",
    event_id: str = "ERP-EVT-2026-90010-1",
    amount: str = "150.00",
    currency: str = "USD",
    account_id: str = "facct_cedarline_legacy",
):
    """Import one settled receipt and return it."""
    result = service.import_payment(
        PaymentEventCommand(
            source_transaction_id=transaction_id,
            source_event_id=event_id,
            event_type="settled",
            amount=amount,
            currency=currency,
            payer_account_id=account_id,
            occurred_at=OCCURRED,
        ),
        administrator,
    )
    assert not isinstance(result, ConflictResult)
    return result


def test_an_allocation_is_confirmed_against_the_assessment(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            link_the_payer(session)
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            assessment = service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            payment = settle_a_payment(session, service, administrator)
            allocation = service.allocate(
                AllocationCommand(
                    payment_id=payment.payment_id,
                    assessment_id=assessment.assessment_id,
                    amount="150.00",
                    idempotency_key="alloc:test:90010",
                ),
                administrator,
            )
            assert not isinstance(allocation, ConflictResult)
            assert allocation.amount_cents == 15000
            assert allocation.status == "active"
            assert allocation.actor_id == "persona_city_administrator"
    finally:
        factory.dispose()


def test_the_same_allocation_command_is_harmless(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            link_the_payer(session)
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            assessment = service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            payment = settle_a_payment(session, service, administrator)
            command = AllocationCommand(
                payment_id=payment.payment_id,
                assessment_id=assessment.assessment_id,
                amount="150.00",
                idempotency_key="alloc:test:90011",
            )
            first = service.allocate(command, administrator)
            second = service.allocate(command, administrator)
            assert not isinstance(first, ConflictResult)
            assert not isinstance(second, ConflictResult)
            assert second.allocation_id == first.allocation_id
            rows = session.execute(
                select(finance.Allocation).where(
                    finance.Allocation.assessment_id == assessment.assessment_id
                )
            ).scalars().all()
            assert len(rows) == 1
    finally:
        factory.dispose()


def test_a_reused_key_with_other_facts_is_a_conflict(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            link_the_payer(session)
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            assessment = service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            payment = settle_a_payment(session, service, administrator)
            service.allocate(
                AllocationCommand(
                    payment_id=payment.payment_id,
                    assessment_id=assessment.assessment_id,
                    amount="150.00",
                    idempotency_key="alloc:test:90012",
                ),
                administrator,
            )
            refused = service.allocate(
                AllocationCommand(
                    payment_id=payment.payment_id,
                    assessment_id=assessment.assessment_id,
                    amount="100.00",
                    idempotency_key="alloc:test:90012",
                ),
                administrator,
            )
            assert isinstance(refused, ConflictResult)
            assert refused.code == "allocation_conflict"
    finally:
        factory.dispose()


def test_an_allocation_beyond_the_available_funds_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            link_the_payer(session)
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            assessment = service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            payment = settle_a_payment(session, service, administrator, amount="150.00")
            with pytest.raises(ValidationError):
                service.allocate(
                    AllocationCommand(
                        payment_id=payment.payment_id,
                        assessment_id=assessment.assessment_id,
                        amount="200.00",
                        idempotency_key="alloc:test:90013",
                    ),
                    administrator,
                )
    finally:
        factory.dispose()


def test_an_unsettled_receipt_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            link_the_payer(session)
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            assessment = service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            received = service.import_payment(
                PaymentEventCommand(
                    source_transaction_id="ERP-TXN-2026-90014",
                    source_event_id="ERP-EVT-2026-90014-1",
                    event_type="received",
                    amount="150.00",
                    payer_account_id="facct_cedarline_legacy",
                    occurred_at=OCCURRED,
                ),
                administrator,
            )
            assert not isinstance(received, ConflictResult)
            with pytest.raises(ValidationError):
                service.allocate(
                    AllocationCommand(
                        payment_id=received.payment_id,
                        assessment_id=assessment.assessment_id,
                        amount="150.00",
                        idempotency_key="alloc:test:90014",
                    ),
                    administrator,
                )
    finally:
        factory.dispose()


def test_a_reversed_receipt_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            link_the_payer(session)
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            assessment = service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            payment = settle_a_payment(
                session,
                service,
                administrator,
                transaction_id="ERP-TXN-2026-90015",
                event_id="ERP-EVT-2026-90015-1",
            )
            service.import_payment(
                PaymentEventCommand(
                    source_transaction_id="ERP-TXN-2026-90015",
                    source_event_id="ERP-EVT-2026-90015-2",
                    event_type="reversed",
                    amount="150.00",
                    payer_account_id="facct_cedarline_legacy",
                    occurred_at=OCCURRED,
                ),
                administrator,
            )
            with pytest.raises(ValidationError):
                service.allocate(
                    AllocationCommand(
                        payment_id=payment.payment_id,
                        assessment_id=assessment.assessment_id,
                        amount="150.00",
                        idempotency_key="alloc:test:90015",
                    ),
                    administrator,
                )
    finally:
        factory.dispose()


def test_a_receipt_in_another_currency_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            link_the_payer(session)
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            assessment = service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            payment = settle_a_payment(
                session,
                service,
                administrator,
                transaction_id="ERP-TXN-2026-90016",
                event_id="ERP-EVT-2026-90016-1",
                currency="EUR",
            )
            with pytest.raises(ValidationError):
                service.allocate(
                    AllocationCommand(
                        payment_id=payment.payment_id,
                        assessment_id=assessment.assessment_id,
                        amount="150.00",
                        currency="EUR",
                        idempotency_key="alloc:test:90016",
                    ),
                    administrator,
                )
    finally:
        factory.dispose()


def test_an_unlinked_payer_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            assessment = service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            payment = settle_a_payment(
                session,
                service,
                administrator,
                transaction_id="ERP-TXN-2026-90017",
                event_id="ERP-EVT-2026-90017-1",
                account_id="facct_quarry",
            )
            with pytest.raises(ValidationError):
                service.allocate(
                    AllocationCommand(
                        payment_id=payment.payment_id,
                        assessment_id=assessment.assessment_id,
                        amount="150.00",
                        idempotency_key="alloc:test:90017",
                    ),
                    administrator,
                )
    finally:
        factory.dispose()


def test_a_superseded_assessment_may_not_receive_an_allocation(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            link_the_payer(session)
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            first = service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            payment = settle_a_payment(session, service, administrator)
            from acme_city.finance.schemas import ReassessmentCommand

            service.reassess(
                ReassessmentCommand(
                    application_id="app_synth_001", valuation="70000.00"
                ),
                administrator,
            )
            with pytest.raises(ValidationError):
                service.allocate(
                    AllocationCommand(
                        payment_id=payment.payment_id,
                        assessment_id=first.assessment_id,
                        amount="150.00",
                        idempotency_key="alloc:test:90018",
                    ),
                    administrator,
                )
    finally:
        factory.dispose()


def test_a_reviewer_may_not_confirm_an_allocation(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            link_the_payer(session)
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            reviewer = context_for(session, "persona_permit_reviewer")
            assessment = service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            payment = settle_a_payment(session, service, administrator)
            with pytest.raises(PermissionDeniedError):
                service.allocate(
                    AllocationCommand(
                        payment_id=payment.payment_id,
                        assessment_id=assessment.assessment_id,
                        amount="150.00",
                        idempotency_key="alloc:test:90019",
                    ),
                    reviewer,
                )
    finally:
        factory.dispose()
