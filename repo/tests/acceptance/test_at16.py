"""AT16: a stale write returns a useful conflict and changes nothing.

Every write of the slice carries the version its author read.  A stale write
is refused with the current version and the difference, and it never
overwrites an accepted change.
"""
# REQUIRES: AT16, CHG-06, ING-03, MDM-05
# A stale write is refused with a structured conflict, and the accepted value
# survives the refusal.

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.changes.router import router as changes_router
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.ingestion.router import router as ingestion_router
from acme_city.persistence.models import change, registry, source
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.registry.router import router as registry_router


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at16.db'}",
            "ACME_SECRET_KEY": "at16-acceptance-secret-value",
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
    app.include_router(registry_router)
    app.include_router(changes_router)
    with TestClient(app) as test_client:
        yield test_client


def select_persona(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def test_at16_a_stale_change_transition_returns_a_conflict(
    client: TestClient, environment: tuple[Settings, FixtureBundle], record_property
) -> None:
    settings, _ = environment
    select_persona(client, "persona_data_steward")
    created = client.post(
        "/api/changes",
        json={
            "target_type": "source_record",
            "target_id": "gis/address_register/GIS-AD-0400",
            "title": "Fictional correction of an official address",
            "reason": "the postcode of the official address is wrong in the demonstration",
            "proposed_value": {"address_id": "GIS-AD-0400"},
        },
    )
    assert created.status_code == 200, created.text
    change_case_id = created.json()["change_case_id"]

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            before = session.execute(
                select(change.ChangeCase).where(
                    change.ChangeCase.id == change_case_id
                )
            ).scalar_one()
            assert before.version == 1
            assert before.status == "requested"

        stale = client.post(
            f"/api/changes/{change_case_id}/transition",
            json={"to_status": "in_review", "expected_version": 99},
        )
        assert stale.status_code == 409
        payload = stale.json()
        assert payload["code"] == "version_conflict"
        assert payload["current_version"] == 1
        assert payload["expected_version"] == 99
        assert payload["differences"]
        assert payload["message"]

        with factory() as session:
            after = session.execute(
                select(change.ChangeCase).where(change.ChangeCase.id == change_case_id)
            ).scalar_one()
            assert after.version == 1
            assert after.status == "requested"
    finally:
        factory.dispose()

    record_property(
        "evidence",
        {
            "change_case_id": change_case_id,
            "expected_version": 99,
            "current_version": 1,
            "status_after_conflict": "requested",
            "mutated": False,
        },
    )


def test_at16_a_stale_source_write_is_a_conflict_and_keeps_the_accepted_value(
    client: TestClient, environment: tuple[Settings, FixtureBundle], record_property
) -> None:
    settings, _ = environment
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/sources/gis/records",
        json={
            "dataset_key": "address_register",
            "record_id": "GIS-AD-0400",
            "expected_version": "1",
            "payload": {
                "address_id": "GIS-AD-0400",
                "street_number": "400",
                "street_name": "Lantern Row",
                "street_type": "Row",
                "municipality": "ACME City",
                "region": "AC",
                "postcode": "ACM-01499",
                "source_string": "400 Lantern Row",
                "parcel_number": "ACME-P-1001",
            },
        },
    )
    assert response.status_code == 200, response.text
    acknowledgement = response.json()
    assert acknowledgement["status"] == "conflict"
    assert acknowledgement["details"]["current_version"] == "5"
    assert acknowledgement["expected_version"] == "1"

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(source.SourceSnapshot).where(
                    source.SourceSnapshot.source_record_id == "GIS-AD-0400",
                    source.SourceSnapshot.source_dataset_id == "address_register",
                    source.SourceSnapshot.record_status == "accepted",
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].source_record_version == "5"
            assert rows[0].raw_payload["postcode"] == "ACM-01401"
    finally:
        factory.dispose()

    record_property(
        "evidence",
        {
            "source_record_id": "GIS-AD-0400",
            "expected_version": "1",
            "current_version": "5",
            "acknowledgement": acknowledgement["status"],
            "accepted_value_kept": True,
        },
    )


def test_at16_a_stale_link_decision_returns_a_conflict(
    client: TestClient, environment: tuple[Settings, FixtureBundle], record_property
) -> None:
    settings, _ = environment
    select_persona(client, "persona_data_steward")
    proposed = client.post(
        "/api/registry/proposals",
        json={
            "source_system_id": "permitting",
            "dataset_key": "applicant_profiles",
            "source_record_id": "PER-AP-0003",
        },
    )
    assert proposed.status_code == 200, proposed.text

    stale = client.post(
        "/api/registry/decisions",
        json={
            "source_system_id": "permitting",
            "source_record_id": "PER-AP-0003",
            "decision": "approve",
            "reason": "a stale read of the link",
            "expected_version": 99,
        },
    )
    assert stale.status_code == 409
    payload = stale.json()
    assert payload["code"] == "version_conflict"
    assert payload["current_version"] == 1

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "PER-AP-0003"
                )
            ).scalars().all()
            assert {row.link_status for row in rows} == {"proposed"}
            assert {row.decision_actor_id for row in rows} == {None}
    finally:
        factory.dispose()

    record_property(
        "evidence",
        {
            "source_record_id": "PER-AP-0003",
            "expected_version": 99,
            "current_version": 1,
            "link_status_after_conflict": "proposed",
            "mutated": False,
        },
    )
