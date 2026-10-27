"""Outbox tests: durability, idempotency and the dependent work of a change."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.changes.dispatcher import ChangeDispatcher, create_publication
from acme_city.changes.schemas import (
    ChangeRequestCommand,
    ChangeTransitionCommand,
)
from acme_city.changes.service import ChangeService
from acme_city.core.errors import ConflictError
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import change
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)

ADDRESS_PAYLOAD = {
    "address_id": "GIS-AD-0400",
    "street_number": "400",
    "street_name": "Lantern Row",
    "street_type": "Row",
    "municipality": "ACME City",
    "region": "AC",
    "postcode": "ACM-01499",
    "source_string": "400 Lantern Row",
    "parcel_number": "ACME-P-1001",
}


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'outbox.db'}",
            "ACME_SECRET_KEY": "outbox-test-secret-value",
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


def steward() -> ActorContext:
    """Return the acting context of the data steward."""
    return ActorContext(actor_id="persona_data_steward")


def delegate() -> ActorContext:
    """Return the acting context of the shared stewardship delegate."""
    return ActorContext(actor_id="service_delegate_steward")


def approved_change(session, payload: dict | None = None) -> change.ChangeCase:
    """Take one factual change from the request to the source command."""
    service = ChangeService(session)
    view = service.request(
        ChangeRequestCommand(
            target_type="source_record",
            target_id="gis/address_register/GIS-AD-0400",
            title="Fictional correction of an official address",
            reason="the postcode of the official address is wrong in the demonstration",
            proposed_value=dict(payload or ADDRESS_PAYLOAD),
        ),
        steward(),
    )
    case_id = view.change_case_id
    service.transition(
        ChangeTransitionCommand(change_case_id=case_id, to_status="in_review"), steward()
    )
    service.transition(
        ChangeTransitionCommand(change_case_id=case_id, to_status="awaiting_approval"),
        steward(),
    )
    service.transition(
        ChangeTransitionCommand(
            change_case_id=case_id,
            to_status="approved",
            approver_actor_id="service_delegate_steward",
        ),
        delegate(),
    )
    service.transition(
        ChangeTransitionCommand(change_case_id=case_id, to_status="sent_to_source"), steward()
    )
    return session.get(change.ChangeCase, case_id)


def test_a_pending_delivery_survives_a_restart(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            case = approved_change(session)
            delivery = create_publication(session, case)
            assert delivery.status == "pending"
            delivery_id = delivery.id
    finally:
        factory.dispose()

    # A new engine stands in for the restarted service.
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            pending = session.execute(
                select(change.OutboxDelivery).where(
                    change.OutboxDelivery.status == "pending"
                )
            ).scalars().all()
            assert [row.id for row in pending] == [delivery_id]
    finally:
        factory.dispose()


def test_an_identical_delivery_reuses_the_key(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            case = approved_change(session)
            first = create_publication(session, case)
            second = create_publication(session, case)
            assert first.id == second.id
            rows = session.execute(
                select(change.OutboxDelivery).where(
                    change.OutboxDelivery.change_case_id == case.id
                )
            ).scalars().all()
            assert len(rows) == 1
    finally:
        factory.dispose()


def test_a_changed_payload_under_the_same_key_is_a_conflict(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            case = approved_change(session)
            create_publication(session, case)
            case.proposed_value = {**dict(case.proposed_value or {}), "postcode": "ACM-01500"}
            case.version = case.version + 1
            session.flush()
            with pytest.raises(ConflictError):
                create_publication(session, case)
    finally:
        factory.dispose()


def test_one_assigned_task_per_dependency(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            case = approved_change(session)
            tasks = session.execute(
                select(change.ReviewTask).where(
                    change.ReviewTask.change_case_id == case.id
                )
            ).scalars().all()
            keys = [task.deduplication_key for task in tasks]
            assert len(keys) == len(set(keys))
            dependencies = session.execute(
                select(change.ChangeDependency).where(
                    change.ChangeDependency.change_case_id == case.id
                )
            ).scalars().all()
            assert dependencies
            assert all(dependency.task_id for dependency in dependencies)
    finally:
        factory.dispose()


def test_the_dispatch_is_idempotent(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            case = approved_change(session)
            first = ChangeDispatcher(session).dispatch_pending()
            assert first.dispatched == 1
            assert first.acknowledged == 1
            assert case.status == "published"

            second = ChangeDispatcher(session).dispatch_pending()
            assert second.dispatched == 0
            assert second.acknowledged == 0

            acknowledgements = session.execute(
                select(change.ConsumerAcknowledgement).where(
                    change.ConsumerAcknowledgement.delivery_id.in_(
                        select(change.OutboxDelivery.id).where(
                            change.OutboxDelivery.change_case_id == case.id
                        )
                    )
                )
            ).scalars().all()
            assert len(acknowledgements) == 1

            deliveries = session.execute(
                select(change.OutboxDelivery).where(
                    change.OutboxDelivery.change_case_id == case.id
                )
            ).scalars().all()
            assert len(deliveries) == 1
            assert deliveries[0].status == "acknowledged"
            assert deliveries[0].attempts == 1
    finally:
        factory.dispose()
