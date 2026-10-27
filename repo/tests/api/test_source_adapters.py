"""Source adapter tests: authorization, expected versions and the acknowledgements."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.ingestion.router import router as ingestion_router
from acme_city.persistence.models import source
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)

PROFILE_PAYLOAD = {
    "party_ref": "party_applicant_1",
    "display_name": "Tamsin Aldous",
    "contact_email": "t.aldous@example.invalid",
    "contact_phone": "+1-555-0141",
    "preferred_contact": "email",
}


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'source-adapters.db'}",
            "ACME_SECRET_KEY": "source-adapter-secret-value",
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
    with TestClient(app) as test_client:
        yield test_client


def select_persona(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def write_record(
    client: TestClient,
    source_system_id: str,
    dataset_key: str,
    record_id: str,
    expected_version: str | None,
    payload: dict,
) -> dict:
    """Write one source record through the local source endpoint."""
    response = client.post(
        f"/api/sources/{source_system_id}/records",
        json={
            "dataset_key": dataset_key,
            "record_id": record_id,
            "expected_version": expected_version,
            "payload": payload,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_source_endpoints_require_a_session(client: TestClient) -> None:
    assert client.get("/api/sources/systems").status_code == 401
    response = client.post(
        "/api/sources/permitting/records",
        json={
            "dataset_key": "applicant_profiles",
            "record_id": "PER-AP-0001",
            "expected_version": "3",
            "payload": PROFILE_PAYLOAD,
        },
    )
    assert response.status_code == 401


def test_an_applicant_may_not_write_to_a_source(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            before = session.execute(
                select(source.SourceSnapshot).where(
                    source.SourceSnapshot.source_record_id == "PER-AP-0001"
                )
            ).scalars().all()
        select_persona(client, "persona_applicant")
        response = client.post(
            "/api/sources/permitting/records",
            json={
                "dataset_key": "applicant_profiles",
                "record_id": "PER-AP-0001",
                "expected_version": "3",
                "payload": PROFILE_PAYLOAD,
            },
        )
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"
        with factory() as session:
            after = session.execute(
                select(source.SourceSnapshot).where(
                    source.SourceSnapshot.source_record_id == "PER-AP-0001"
                )
            ).scalars().all()
        assert len(after) == len(before)
    finally:
        factory.dispose()


def test_an_authorized_write_is_accepted_and_advances_the_version(
    client: TestClient,
) -> None:
    select_persona(client, "persona_data_steward")
    payload = {**PROFILE_PAYLOAD, "contact_email": "t.aldous+new@example.invalid"}
    acknowledgement = write_record(
        client, "permitting", "applicant_profiles", "PER-AP-0001", "3", payload
    )
    assert acknowledgement["status"] == "accepted"
    assert acknowledgement["source_record_version"] == "4"
    assert acknowledgement["expected_version"] == "3"


def test_a_stale_expected_version_is_a_conflict(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    acknowledgement = write_record(
        client, "permitting", "applicant_profiles", "PER-AP-0001", "1", PROFILE_PAYLOAD
    )
    assert acknowledgement["status"] == "conflict"
    assert acknowledgement["details"]["current_version"] == "3"
    assert acknowledgement["source_record_version"] == "3"


def test_a_refused_write_keeps_the_accepted_value(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    payload = {**PROFILE_PAYLOAD, "_demo_control": "reject"}
    acknowledgement = write_record(
        client, "permitting", "applicant_profiles", "PER-AP-0001", "3", payload
    )
    assert acknowledgement["status"] == "rejected"
    assert acknowledgement["details"]["reason"] == "source_refused"
    assert acknowledgement["source_record_version"] == "3"


def test_a_source_that_does_not_answer_is_a_timeout(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    payload = {**PROFILE_PAYLOAD, "_demo_control": "timeout"}
    acknowledgement = write_record(
        client, "permitting", "applicant_profiles", "PER-AP-0001", "3", payload
    )
    assert acknowledgement["status"] == "timeout"
    assert acknowledgement["source_record_version"] == "3"


def test_an_invalid_payload_is_refused_by_the_source(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    payload = {**PROFILE_PAYLOAD, "preferred_contact": "carrier_pigeon"}
    acknowledgement = write_record(
        client, "permitting", "applicant_profiles", "PER-AP-0001", "3", payload
    )
    assert acknowledgement["status"] == "rejected"
    codes = {error["error_code"] for error in acknowledgement["details"]["field_errors"]}
    assert "unsupported_value" in codes


def test_gis_refuses_a_write_that_drops_the_unit(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    acknowledgement = write_record(
        client,
        "gis",
        "address_register",
        "GIS-AD-0400-U2",
        "3",
        {
            "address_id": "GIS-AD-0400-U2",
            "street_number": "400",
            "street_name": "Lantern Row",
            "street_type": "Row",
            "municipality": "ACME City",
            "region": "AC",
            "postcode": "ACM-01401",
            "source_string": "400 Lantern Row",
            "parcel_number": "ACME-P-1001",
        },
    )
    assert acknowledgement["status"] == "rejected"
    assert acknowledgement["details"]["reason"] == "unit_distinction_required"


def test_erp_finance_refuses_to_rewrite_a_settled_receipt(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    acknowledgement = write_record(
        client,
        "erp_finance",
        "payment_events",
        "ERP-EVT-2026-04517-2",
        "2",
        {
            "source_event_id": "ERP-EVT-2026-04517-2",
            "source_transaction_id": "ERP-TXN-2026-04517",
            "event_type": "settled",
            "amount": 150.0,
            "amount_cents": 15000,
            "currency": "USD",
            "source_account_id": "ERP-ACC-77120-LEG",
            "paid_at": "2026-09-14T15:20:00Z",
        },
    )
    assert acknowledgement["status"] == "rejected"
    assert acknowledgement["details"]["reason"] == "append_only_receipt"


def test_the_source_systems_are_listed_as_simulated(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    response = client.get("/api/sources/systems")
    assert response.status_code == 200
    systems = {row["source_system_id"]: row for row in response.json()["source_systems"]}
    assert systems["permitting"]["simulated"] is True
    assert systems["gis"]["simulated"] is True
    assert systems["erp_finance"]["simulated"] is True
