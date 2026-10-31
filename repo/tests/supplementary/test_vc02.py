"""VC02: the source observations carry their denominators and their times.

Every intake reports how many records it received, accepted, left unchanged,
quarantined and held as history, and the source time, the effective time and
the receipt time stay apart.
"""
# REQUIRES: VC02, ING-05
# The intake reports its denominators as counted observations and keeps the
# source, effective and receipt times apart.

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.ingestion.router import router as ingestion_router
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'vc02.db'}",
            "ACME_SECRET_KEY": "vc02-supplementary-secret-value",
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


PROFILE = {
    "party_ref": "party_applicant_1",
    "display_name": "Demo Applicant",
    "contact_email": "demo.applicant@example.invalid",
    "contact_phone": "+1-555-0141",
    "preferred_contact": "email",
}


def test_vc02_the_observations_report_the_denominators(client: TestClient) -> None:
    response = client.post("/api/session/select", json={"actor_id": "persona_data_steward"})
    assert response.status_code == 200, response.text
    ingested = client.post(
        "/api/sources/permitting/applicant_profiles/intake",
        json={
            "records": [
                {
                    "source_record_id": "PER-AP-VC02-0001",
                    "source_record_version": "1",
                    "payload": dict(PROFILE),
                },
                {
                    "source_record_id": "PER-AP-VC02-0002",
                    "source_record_version": "1",
                    "payload": {**PROFILE, "party_ref": "party_applicant_2"},
                },
                {
                    "source_record_id": "PER-AP-VC02-0003",
                    "source_record_version": "1",
                    "payload": {**PROFILE, "preferred_contact": "carrier_pigeon"},
                },
            ]
        },
    )
    assert ingested.status_code == 200, ingested.text
    payload = ingested.json()
    assert payload["received"] == 3
    assert payload["accepted"] == 2
    assert payload["quarantined"] == 1
    assert (
        payload["accepted"]
        + payload["unchanged"]
        + payload["quarantined"]
        + payload["unresolved"]
        + payload["staged"]
        == payload["received"]
    )

    observations = client.get(
        "/api/sources/permitting/applicant_profiles/observations"
    ).json()["observations"]
    metrics = {row["metric"]: row for row in observations}
    assert metrics["records_received"]["numerator"] == 3
    assert metrics["records_received"]["denominator"] == 3
    assert metrics["records_accepted"]["numerator"] == 2
    assert metrics["records_accepted"]["denominator"] == 3
    assert metrics["records_quarantined"]["numerator"] == 1
    assert metrics["records_quarantined"]["denominator"] == 3
    for row in observations:
        assert row["denominator"] == 3
        assert row["observed_at"]
        assert row["received_at"]


def test_vc02_the_source_effective_and_receipt_times_stay_apart(
    client: TestClient,
) -> None:
    response = client.post("/api/session/select", json={"actor_id": "persona_data_steward"})
    assert response.status_code == 200, response.text
    ingested = client.post(
        "/api/sources/permitting/applicant_profiles/intake",
        json={
            "received_at": "2026-10-20T09:00:00Z",
            "records": [
                {
                    "source_record_id": "PER-AP-VC02-0004",
                    "source_record_version": "1",
                    "payload": dict(PROFILE),
                    "source_updated_at": "2026-09-05T13:12:00Z",
                    "effective_from": "2026-09-05T00:00:00Z",
                }
            ],
        },
    )
    assert ingested.status_code == 200, ingested.text
    snapshots = client.get(
        "/api/sources/permitting/applicant_profiles/snapshots",
        params={"record_id": "PER-AP-VC02-0004"},
    ).json()["snapshots"]
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot["source_updated_at"] == "2026-09-05T13:12:00Z"
    assert snapshot["effective_from"] == "2026-09-05T00:00:00Z"
    assert snapshot["ingested_at"] == "2026-10-20T09:00:00Z"
    assert snapshot["effective_to"] is None


def test_vc02_an_unknown_business_time_stays_empty(client: TestClient) -> None:
    response = client.post("/api/session/select", json={"actor_id": "persona_data_steward"})
    assert response.status_code == 200, response.text
    client.post(
        "/api/sources/permitting/applicant_profiles/intake",
        json={
            "records": [
                {
                    "source_record_id": "PER-AP-VC02-0005",
                    "source_record_version": "1",
                    "payload": dict(PROFILE),
                }
            ]
        },
    )
    snapshots = client.get(
        "/api/sources/permitting/applicant_profiles/snapshots",
        params={"record_id": "PER-AP-VC02-0005"},
    ).json()["snapshots"]
    assert len(snapshots) == 1
    assert snapshots[0]["source_updated_at"] is None
    assert snapshots[0]["effective_from"] is None
    assert snapshots[0]["effective_to"] is None
    assert snapshots[0]["ingested_at"] is not None
