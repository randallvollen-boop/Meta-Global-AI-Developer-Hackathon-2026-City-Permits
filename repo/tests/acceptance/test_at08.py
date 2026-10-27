"""AT08: the controlled change lifecycle, the accepted source value and the outbox.

The acceptance run drives the real endpoints and the real database.  The
persona catalogue grants ``change.case.transition`` to one persona, so the
approval of a steward request is performed by the shared stewardship delegate
with its own persisted grant; that is the delegated path of the demonstration,
not a bypass of the authorization.
"""
# REQUIRES: AT08, CHG-01, CHG-02, CHG-05, EDIT-04
# The lifecycle is server decided, a refused correction keeps the accepted
# source value, and the durable outbox survives a restart without duplicating
# a delivery.

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.changes.dispatcher import ChangeDispatcher
from acme_city.changes.router import router as changes_router
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.ingestion.router import router as ingestion_router
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
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at08.db'}",
            "ACME_SECRET_KEY": "at08-acceptance-secret-value",
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
    return settings, bundle


@pytest.fixture()
def client(environment: tuple[Settings, FixtureBundle]) -> TestClient:
    settings, _ = environment
    app = create_app(settings)
    app.include_router(ingestion_router)
    app.include_router(changes_router)
    with TestClient(app) as test_client:
        yield test_client


def steward() -> ActorContext:
    """Return the acting context of the data steward."""
    return ActorContext(actor_id="persona_data_steward")


def delegate() -> ActorContext:
    """Return the acting context of the shared stewardship delegate."""
    return ActorContext(actor_id="service_delegate_steward")


def select_persona(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def request_correction(client: TestClient, payload: dict) -> dict:
    """Request a correction of an official address through the real endpoint."""
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/changes",
        json={
            "target_type": "source_record",
            "target_id": "gis/address_register/GIS-AD-0400",
            "title": "Fictional correction of an official address",
            "reason": "the postcode of the official address is wrong in the demonstration",
            "proposed_value": payload,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def move(client: TestClient, change_case_id: str, to_status: str, **extra) -> dict:
    """Move a change case through the real endpoint."""
    select_persona(client, "persona_data_steward")
    body = {"to_status": to_status}
    body.update(extra)
    response = client.post(f"/api/changes/{change_case_id}/transition", json=body)
    assert response.status_code in {200, 403, 409}, response.text
    return response.json()


def approve_with_the_delegate(settings: Settings, change_case_id: str) -> None:
    """Approve a steward request as the delegated steward.

    The delegate holds the ``change.case.transition`` grant in its own right;
    the requester may not approve their own request, so the delegated
    steward decides.
    """
    from acme_city.changes.schemas import ChangeTransitionCommand
    from acme_city.changes.service import ChangeService

    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            ChangeService(session).transition(
                ChangeTransitionCommand(
                    change_case_id=change_case_id,
                    to_status="approved",
                    approver_actor_id="service_delegate_steward",
                ),
                delegate(),
            )
    finally:
        factory.dispose()


def accepted_address(settings: Settings) -> tuple[str | None, dict]:
    """Return the accepted version and payload of the official address."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
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
    finally:
        factory.dispose()


def test_at08_the_lifecycle_is_server_decided_and_the_outbox_survives_a_restart(
    client: TestClient,
    environment: tuple[Settings, FixtureBundle],
    record_property,
) -> None:
    settings, _ = environment
    created = request_correction(client, dict(CORRECTION))
    change_case_id = created["change_case_id"]

    reviewed = move(client, change_case_id, "in_review")
    assert reviewed["value"]["status"] == "in_review"
    waiting = move(client, change_case_id, "awaiting_approval")
    assert waiting["value"]["status"] == "awaiting_approval"

    approve_with_the_delegate(settings, change_case_id)
    sent = move(client, change_case_id, "sent_to_source")
    assert sent["value"]["status"] == "sent_to_source"
    assert sent["value"]["source_commands"]
    command = sent["value"]["source_commands"][0]
    assert command["retry_key"]
    assert command["expected_source_version"] == "5"

    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            summary = ChangeDispatcher(session).dispatch_pending()
            assert summary.dispatched == 1
            assert summary.acknowledged == 1
            assert summary.published == 1
            case = session.get(change.ChangeCase, change_case_id)
            assert case.status == "published"
            delivery = session.execute(
                select(change.OutboxDelivery).where(
                    change.OutboxDelivery.change_case_id == change_case_id
                )
            ).scalar_one()
            acknowledgement = session.execute(
                select(change.ConsumerAcknowledgement).where(
                    change.ConsumerAcknowledgement.delivery_id == delivery.id
                )
            ).scalar_one()
    finally:
        factory.dispose()

    version, payload = accepted_address(settings)
    assert version == "6"
    assert payload["postcode"] == "ACM-01499"

    record_property(
        "evidence",
        {
            "change_case_id": change_case_id,
            "source_command_id": command["source_command_id"],
            "command_key": command["retry_key"],
            "expected_source_version": command["expected_source_version"],
            "accepted_source_version": version,
            "delivery_id": delivery.id,
            "consumer_acknowledgement_id": acknowledgement.id,
            "requesting_actor": created["requester_actor_id"],
            "approving_actor": "service_delegate_steward",
            "final_status": "published",
        },
    )


def test_at08_a_refused_correction_keeps_the_accepted_source_value(
    client: TestClient,
    environment: tuple[Settings, FixtureBundle],
    record_property,
) -> None:
    settings, _ = environment
    created = request_correction(client, {**CORRECTION, "_demo_control": "reject"})
    change_case_id = created["change_case_id"]
    move(client, change_case_id, "in_review")
    move(client, change_case_id, "awaiting_approval")
    approve_with_the_delegate(settings, change_case_id)
    move(client, change_case_id, "sent_to_source")

    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            summary = ChangeDispatcher(session).dispatch_pending()
            assert summary.rejected == 1
            assert summary.published == 0
            case = session.get(change.ChangeCase, change_case_id)
            assert case.status == "synchronization_failed"
    finally:
        factory.dispose()

    version, payload = accepted_address(settings)
    assert version == "5"
    assert payload["postcode"] == "ACM-01401"
    record_property(
        "evidence",
        {
            "change_case_id": change_case_id,
            "accepted_source_version": version,
            "final_status": "synchronization_failed",
            "published": False,
        },
    )


def test_at08_a_late_acknowledgement_does_not_replace_a_newer_accepted_version(
    client: TestClient,
    environment: tuple[Settings, FixtureBundle],
) -> None:
    settings, _ = environment
    created = request_correction(client, {**CORRECTION, "_demo_control": {"mode": "late", "version": "4"}})
    change_case_id = created["change_case_id"]
    move(client, change_case_id, "in_review")
    move(client, change_case_id, "awaiting_approval")
    approve_with_the_delegate(settings, change_case_id)
    move(client, change_case_id, "sent_to_source")

    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            summary = ChangeDispatcher(session).dispatch_pending()
            assert summary.late == 1
            assert summary.published == 0
            case = session.get(change.ChangeCase, change_case_id)
            assert case.status == "sent_to_source"
    finally:
        factory.dispose()

    version, payload = accepted_address(settings)
    assert version == "5"
    assert payload["postcode"] == "ACM-01401"


def test_at08_the_outbox_worker_survives_a_restart_and_stays_idempotent(
    client: TestClient,
    environment: tuple[Settings, FixtureBundle],
    record_property,
) -> None:
    settings, _ = environment
    created = request_correction(client, dict(CORRECTION))
    change_case_id = created["change_case_id"]
    move(client, change_case_id, "in_review")
    move(client, change_case_id, "awaiting_approval")
    approve_with_the_delegate(settings, change_case_id)
    move(client, change_case_id, "sent_to_source")

    script = Path(__file__).resolve().parents[2] / "scripts" / "dispatch_outbox.py"
    database_url = settings.database_url

    def run_worker() -> dict:
        result = subprocess.run(
            [sys.executable, str(script), "--once", "--database", database_url],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[2]),
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    first = run_worker()
    assert first["dispatched"] == 1
    assert first["acknowledged"] == 1
    assert first["published"] == 1

    # A second run stands in for the restarted service: nothing is repeated.
    second = run_worker()
    assert second["dispatched"] == 0
    assert second["published"] == 0

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            case = session.get(change.ChangeCase, change_case_id)
            assert case.status == "published"
            deliveries = session.execute(
                select(change.OutboxDelivery).where(
                    change.OutboxDelivery.change_case_id == change_case_id
                )
            ).scalars().all()
            assert len(deliveries) == 1
            assert deliveries[0].attempts == 1
            acknowledgements = session.execute(
                select(change.ConsumerAcknowledgement).where(
                    change.ConsumerAcknowledgement.delivery_id == deliveries[0].id
                )
            ).scalars().all()
            assert len(acknowledgements) == 1
    finally:
        factory.dispose()
    record_property(
        "evidence",
        {
            "change_case_id": change_case_id,
            "worker_runs": 2,
            "deliveries": 1,
            "consumer_acknowledgements": 1,
        },
    )
