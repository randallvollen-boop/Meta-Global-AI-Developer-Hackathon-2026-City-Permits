"""D08: a replayed import, command or publication duplicates nothing.

The same delivery is delivered once, the same import is stored once, and the
same steward decision leaves one active link.  The replay is visible as an
unchanged record, never as a second one.
"""
# REQUIRES: D08, CHG-05, ING-03, MDM-01
# A replay reuses the existing record, task and delivery instead of creating a
# second one.

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
from acme_city.ingestion.schemas import IngestCommand, SourceRecordCommand
from acme_city.ingestion.service import IngestionService
from acme_city.persistence.models import change, registry, source
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.registry.schemas import MatchDecisionCommand, MatchProposalCommand
from acme_city.registry.service import RegistryService

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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'd08.db'}",
            "ACME_SECRET_KEY": "d08-scenario-secret-value",
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


def test_a_replayed_import_stores_no_second_snapshot(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = IngestionService(session)
            payload = {
                "party_ref": "party_applicant_1",
                "display_name": "Tamsin Aldous",
                "contact_email": "t.aldous@example.invalid",
                "contact_phone": "+1-555-0141",
                "preferred_contact": "email",
            }
            command = IngestCommand(
                source_system_id="permitting",
                dataset_key="applicant_profiles",
                records=[
                    SourceRecordCommand(
                        source_record_id="PER-AP-REPLAY-0001",
                        source_record_version="1",
                        payload=dict(payload),
                    )
                ],
            )
            first = service.ingest(command, steward())
            assert first.accepted == 1
            second = service.ingest(command, steward())
            assert second.unchanged == 1
            assert second.accepted == 0
            assert second.snapshot_ids == first.snapshot_ids

            snapshots = session.execute(
                select(source.SourceSnapshot).where(
                    source.SourceSnapshot.source_record_id == "PER-AP-REPLAY-0001"
                )
            ).scalars().all()
            assert len(snapshots) == 1
    finally:
        factory.dispose()


def test_a_replayed_command_sends_one_command_and_one_acknowledgement(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = ChangeService(session)
            view = service.request(
                ChangeRequestCommand(
                    target_type="source_record",
                    target_id="gis/address_register/GIS-AD-0400",
                    title="Fictional correction of an official address",
                    reason="the postcode of the official address is wrong in the demonstration",
                    proposed_value=dict(CORRECTION),
                ),
                steward(),
            )
            case_id = view.change_case_id
            service.transition(
                ChangeTransitionCommand(change_case_id=case_id, to_status="in_review"),
                steward(),
            )
            service.transition(
                ChangeTransitionCommand(
                    change_case_id=case_id, to_status="awaiting_approval"
                ),
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
                ChangeTransitionCommand(
                    change_case_id=case_id, to_status="sent_to_source"
                ),
                steward(),
            )
            commands = session.execute(
                select(change.SourceCommand).where(
                    change.SourceCommand.change_case_id == case_id
                )
            ).scalars().all()
            assert len(commands) == 1
            retry_key = commands[0].retry_key

            first = ChangeDispatcher(session).dispatch_pending()
            assert first.dispatched == 1
            second = ChangeDispatcher(session).dispatch_pending()
            assert second.dispatched == 0
            assert second.published == 0

            after = session.execute(
                select(change.SourceCommand).where(
                    change.SourceCommand.change_case_id == case_id
                )
            ).scalars().all()
            assert len(after) == 1
            assert after[0].retry_key == retry_key
            assert after[0].status == "accepted"

            deliveries = session.execute(
                select(change.OutboxDelivery).where(
                    change.OutboxDelivery.change_case_id == case_id
                )
            ).scalars().all()
            assert len(deliveries) == 1
            acknowledgements = session.execute(
                select(change.ConsumerAcknowledgement).where(
                    change.ConsumerAcknowledgement.delivery_id == deliveries[0].id
                )
            ).scalars().all()
            assert len(acknowledgements) == 1
    finally:
        factory.dispose()


def test_a_replayed_decision_leaves_one_active_link(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = RegistryService(session)
            for _ in range(2):
                service.propose(
                    MatchProposalCommand(
                        source_system_id="permitting",
                        dataset_key="applicant_profiles",
                        source_record_id="PER-AP-0003",
                    ),
                    steward(),
                )
                service.decide(
                    MatchDecisionCommand(
                        source_system_id="permitting",
                        source_record_id="PER-AP-0003",
                        decision="approve",
                        reason="fictional demonstration of a replayed decision",
                        evidence=[
                            {"field": "party_ref", "value": "party_cedarline"}
                        ],
                    ),
                    steward(),
                )
            rows = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "PER-AP-0003"
                )
            ).scalars().all()
            approved = [row for row in rows if row.link_status == "approved"]
            assert len(approved) == 1
            assert len(rows) == 1
    finally:
        factory.dispose()
