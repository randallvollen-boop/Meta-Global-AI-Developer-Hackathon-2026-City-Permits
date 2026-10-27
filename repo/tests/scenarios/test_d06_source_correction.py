"""D06: a refused or delayed source correction keeps the accepted value.

The correction reaches the source, the source refuses it, and the case says
so.  The accepted value of the official address is untouched, and the
dependent work is the only thing that is held up.
"""
# REQUIRES: D06, CHG-02, CHG-04, EDIT-04
# A refused or delayed correction keeps the accepted source value and reports a
# truthful failed state instead of a published one.

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.changes.dispatcher import ChangeDispatcher
from acme_city.changes.schemas import ChangeRequestCommand, ChangeTransitionCommand
from acme_city.changes.service import ChangeService
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import change, source
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)

CORRECTION = {
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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'd06.db'}",
            "ACME_SECRET_KEY": "d06-scenario-secret-value",
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


def sent_change(session, payload: dict) -> change.ChangeCase:
    """Take a factual change from the request to the source command."""
    service = ChangeService(session)
    view = service.request(
        ChangeRequestCommand(
            target_type="source_record",
            target_id="gis/address_register/GIS-AD-0400",
            title="Fictional correction of an official address",
            reason="the postcode of the official address is wrong in the demonstration",
            proposed_value=dict(payload),
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


def accepted_address(session) -> tuple[str | None, dict]:
    """Return the accepted version and payload of the official address."""
    rows = session.execute(
        select(source.SourceSnapshot).where(
            source.SourceSnapshot.source_system_id == "gis",
            source.SourceSnapshot.source_dataset_id == "address_register",
            source.SourceSnapshot.source_record_id == "GIS-AD-0400",
            source.SourceSnapshot.record_status == "accepted",
        )
    ).scalars().all()
    if not rows:
        return None, {}
    current = max(rows, key=lambda row: row.source_record_version or "")
    return current.source_record_version, dict(current.raw_payload or {})


def test_a_refused_correction_keeps_the_accepted_value(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            case = sent_change(session, {**CORRECTION, "_demo_control": "reject"})
            assert case.status == "sent_to_source"

            summary = ChangeDispatcher(session).dispatch_pending()
            assert summary.dispatched == 1
            assert summary.rejected == 1
            assert summary.published == 0

            refreshed = session.get(change.ChangeCase, case.id)
            assert refreshed.status == "synchronization_failed"

            version, payload = accepted_address(session)
            assert version == "5"
            assert payload["postcode"] == "ACM-01401"
    finally:
        factory.dispose()


def test_a_delayed_correction_keeps_the_accepted_value(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            case = sent_change(session, {**CORRECTION, "_demo_control": "timeout"})
            summary = ChangeDispatcher(session).dispatch_pending()
            assert summary.timed_out == 1
            assert summary.published == 0

            refreshed = session.get(change.ChangeCase, case.id)
            assert refreshed.status == "synchronization_failed"

            version, payload = accepted_address(session)
            assert version == "5"
            assert payload["postcode"] == "ACM-01401"
    finally:
        factory.dispose()


def test_a_refused_correction_is_never_published(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            case = sent_change(session, {**CORRECTION, "_demo_control": "reject"})
            ChangeDispatcher(session).dispatch_pending()
            deliveries = session.execute(
                select(change.OutboxDelivery).where(
                    change.OutboxDelivery.change_case_id == case.id
                )
            ).scalars().all()
            assert deliveries == []
            commands = session.execute(
                select(change.SourceCommand).where(
                    change.SourceCommand.change_case_id == case.id
                )
            ).scalars().all()
            assert len(commands) == 1
            assert commands[0].status == "rejected"
            assert commands[0].response["status"] == "rejected"
    finally:
        factory.dispose()


def test_an_accepted_correction_is_published_after_the_source_acknowledges(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            case = sent_change(session, CORRECTION)
            summary = ChangeDispatcher(session).dispatch_pending()
            assert summary.acknowledged == 1
            assert summary.published == 1

            refreshed = session.get(change.ChangeCase, case.id)
            assert refreshed.status == "published"

            version, payload = accepted_address(session)
            assert version == "6"
            assert payload["postcode"] == "ACM-01499"
    finally:
        factory.dispose()
