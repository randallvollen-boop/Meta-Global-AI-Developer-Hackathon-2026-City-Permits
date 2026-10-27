"""Payment event tests: a stable receipt and an append-only history.

A receipt keeps its identity while its settlement and reversal events are
appended to its history.  The same event delivered twice returns the same
receipt, and the same event identifier with different facts is a conflict.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import ValidationError
from acme_city.core.results import ConflictResult
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.finance.schemas import PaymentEventCommand
from acme_city.finance.service import FinanceService
from acme_city.persistence.models import finance
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

OCCURRED = datetime(2026, 9, 14, 15, 20, tzinfo=UTC)


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'payments.db'}",
            "ACME_SECRET_KEY": "payment-events-test-secret-value",
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


def event(
    event_id: str = "ERP-EVT-2026-90001-1",
    transaction_id: str = "ERP-TXN-2026-90001",
    event_type: str = "received",
    amount: str = "150.00",
    currency: str = "USD",
    version: str | None = "1",
) -> PaymentEventCommand:
    """Return one simulated source payment event."""
    return PaymentEventCommand(
        source_transaction_id=transaction_id,
        source_event_id=event_id,
        source_event_version=version,
        event_type=event_type,
        amount=amount,
        currency=currency,
        payer_account_id="facct_cedarline_legacy",
        occurred_at=OCCURRED,
    )


def test_a_new_event_creates_one_receipt(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            payment = service.import_payment(event(), administrator)
            assert not isinstance(payment, ConflictResult)
            assert payment.amount == "150.00"
            assert payment.amount_cents == 15000
            assert payment.settlement_status == "unsettled"
            assert len(payment.events) == 1
    finally:
        factory.dispose()


def test_the_same_event_delivered_twice_returns_the_same_receipt(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            first = service.import_payment(event(), administrator)
            second = service.import_payment(event(), administrator)
            assert not isinstance(first, ConflictResult)
            assert not isinstance(second, ConflictResult)
            assert second.payment_id == first.payment_id
            assert len(second.events) == 1

            count = session.execute(
                select(func.count())
                .select_from(finance.PaymentEvent)
                .where(finance.PaymentEvent.payment_id == first.payment_id)
            ).scalar_one()
            assert count == 1
    finally:
        factory.dispose()


def test_a_settlement_event_is_appended_to_the_receipt(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            received = service.import_payment(event(), administrator)
            settled = service.import_payment(
                event(
                    event_id="ERP-EVT-2026-90001-2",
                    event_type="settled",
                    version="2",
                ),
                administrator,
            )
            assert not isinstance(settled, ConflictResult)
            assert settled.payment_id == received.payment_id
            assert settled.settlement_status == "settled"
            assert [item.event_type for item in settled.events] == ["received", "settled"]
            assert settled.paid_at is not None
    finally:
        factory.dispose()


def test_a_reversal_is_appended_and_reopens_the_exception(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            service.import_payment(
                event(event_id="ERP-EVT-2026-90002-1", transaction_id="ERP-TXN-2026-90002",
                      event_type="settled"),
                administrator,
            )
            reversed_payment = service.import_payment(
                event(
                    event_id="ERP-EVT-2026-90002-2",
                    transaction_id="ERP-TXN-2026-90002",
                    event_type="reversed",
                    version="2",
                ),
                administrator,
            )
            assert not isinstance(reversed_payment, ConflictResult)
            assert reversed_payment.settlement_status == "reversed"
            assert [item.event_type for item in reversed_payment.events] == [
                "settled",
                "reversed",
            ]
    finally:
        factory.dispose()


def test_the_same_event_identifier_with_other_facts_is_a_conflict(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            service.import_payment(event(), administrator)
            refused = service.import_payment(event(amount="200.00"), administrator)
            assert isinstance(refused, ConflictResult)
            assert refused.code == "payment_event_conflict"
    finally:
        factory.dispose()


def test_a_second_currency_for_one_receipt_is_a_conflict(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            service.import_payment(event(), administrator)
            refused = service.import_payment(
                event(
                    event_id="ERP-EVT-2026-90001-2",
                    event_type="settled",
                    currency="EUR",
                    version="2",
                ),
                administrator,
            )
            assert isinstance(refused, ConflictResult)
            assert refused.code == "payment_currency_conflict"
    finally:
        factory.dispose()


def test_an_unsupported_event_type_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = FinanceService(session)
            administrator = context_for(session, "persona_city_administrator")
            with pytest.raises(ValidationError):
                service.import_payment(event(event_type="teleported"), administrator)
    finally:
        factory.dispose()


def test_an_applicant_may_not_import_a_payment(seeded: Settings) -> None:
    from acme_city.core.errors import PermissionDeniedError

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = FinanceService(session)
            applicant = context_for(session, "persona_applicant")
            with pytest.raises(PermissionDeniedError):
                service.import_payment(event(), applicant)
    finally:
        factory.dispose()
