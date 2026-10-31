"""AT05: the intake is idempotent and the identities are immutable and typed.

A repeated delivery changes nothing, a changed or late delivery is preserved
as history, and a canonical identity keeps its type and its identifier while
its links stay versioned.
"""
# REQUIRES: AT05, ING-03, MDM-01
# Ingestion is idempotent, changed and late versions are preserved, and the
# canonical identities and their crosswalks keep their identifiers and versions.

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.ingestion.router import router as ingestion_router
from acme_city.persistence.models import registry, source
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.registry.router import router as registry_router

PROFILE = {
    "party_ref": "party_applicant_1",
    "display_name": "Demo Applicant",
    "contact_email": "demo.applicant@example.invalid",
    "contact_phone": "+1-555-0141",
    "preferred_contact": "email",
}


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at05.db'}",
            "ACME_SECRET_KEY": "at05-acceptance-secret-value",
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
    with TestClient(app) as test_client:
        yield test_client


def select_persona(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def intake(client: TestClient, record_id: str, version: str, payload: dict) -> dict:
    """Ingest one source record through the real endpoint."""
    response = client.post(
        "/api/sources/permitting/applicant_profiles/intake",
        json={
            "records": [
                {
                    "source_record_id": record_id,
                    "source_record_version": version,
                    "payload": payload,
                    "source_updated_at": "2026-10-20T08:00:00Z",
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_at05_a_repeated_delivery_is_unchanged(client: TestClient, record_property) -> None:
    select_persona(client, "persona_data_steward")
    first = intake(client, "PER-AP-AT05-0001", "1", dict(PROFILE))
    assert first["accepted"] == 1
    second = intake(client, "PER-AP-AT05-0001", "1", dict(PROFILE))
    assert second["unchanged"] == 1
    assert second["accepted"] == 0
    assert second["snapshot_ids"] == first["snapshot_ids"]
    record_property(
        "evidence",
        {
            "source_record_id": "PER-AP-AT05-0001",
            "ingestion_run_id": first["ingestion_run_id"],
            "snapshot_id": first["snapshot_ids"][0],
            "received": second["received"],
            "accepted": second["accepted"],
            "unchanged": second["unchanged"],
        },
    )


def test_at05_a_changed_version_is_preserved_as_a_second_snapshot(
    client: TestClient,
) -> None:
    select_persona(client, "persona_data_steward")
    intake(client, "PER-AP-AT05-0002", "1", dict(PROFILE))
    changed = intake(
        client,
        "PER-AP-AT05-0002",
        "2",
        {**PROFILE, "contact_email": "demo.applicant+second@example.invalid"},
    )
    assert changed["accepted"] == 1
    snapshots = client.get(
        "/api/sources/permitting/applicant_profiles/snapshots",
        params={"record_id": "PER-AP-AT05-0002"},
    ).json()["snapshots"]
    assert len(snapshots) == 2
    assert {row["source_record_version"] for row in snapshots} == {"1", "2"}
    assert snapshots[0]["raw_payload"]["contact_email"] == "demo.applicant@example.invalid"
    assert snapshots[1]["raw_payload"]["contact_email"] == "demo.applicant+second@example.invalid"


def test_at05_a_late_version_is_history_only(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    intake(client, "PER-AP-AT05-0003", "3", dict(PROFILE))
    late = intake(
        client,
        "PER-AP-AT05-0003",
        "2",
        {**PROFILE, "contact_phone": "+1-555-0000"},
        )
    assert late["unresolved"] == 1
    assert late["accepted"] == 0
    assert late["issue_ids"]

    snapshots = client.get(
        "/api/sources/permitting/applicant_profiles/snapshots",
        params={"record_id": "PER-AP-AT05-0003"},
    ).json()["snapshots"]
    statuses = {row["source_record_version"]: row["record_status"] for row in snapshots}
    assert statuses["2"] == "unresolved"
    assert statuses["3"] == "accepted"


def test_at05_the_canonical_identities_are_typed_and_immutable(
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
    decided = client.post(
        "/api/registry/decisions",
        json={
            "source_system_id": "permitting",
            "source_record_id": "PER-AP-0003",
            "decision": "approve",
            "reason": "the declared reference and the recorded alias agree",
        },
    )
    assert decided.status_code == 200, decided.text

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            entities = session.execute(
                select(registry.CanonicalEntity)
            ).scalars().all()
            types = {row.entity_id: row.entity_type for row in entities}
            assert types["party_cedarline"] == "party"
            assert types["party_false_friend"] == "party"
            links = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "PER-AP-0003"
                )
            ).scalars().all()
            assert len(links) == 1
            assert links[0].entity_id == "party_cedarline"
            assert links[0].version >= 1
            assert links[0].link_status == "approved"
    finally:
        factory.dispose()
    record_property(
        "evidence",
        {
            "canonical_entity_id": "party_cedarline",
            "entity_type": "party",
            "crosswalk_version": links[0].version,
            "link_status": links[0].link_status,
        },
    )
