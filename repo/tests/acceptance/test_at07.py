"""AT07: the trusted view follows the declared authority and keeps the doubt.

The view shows the value the published authority policy names, records where
it came from, keeps the disagreement with every other source visible, and
never invents a value that no source delivered.
"""
# REQUIRES: AT07, MDM-04, GOV-05
# The trusted view follows the authority policy, records the provenance of
# every value, preserves the disagreement and raises a blocking issue when the
# authority of a field is unresolved.

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
from acme_city.persistence.models import change, registry
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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at07.db'}",
            "ACME_SECRET_KEY": "at07-acceptance-secret-value",
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


def approve(client: TestClient, source_system_id: str, dataset_key: str, record_id: str) -> None:
    """Propose and approve one source link through the real endpoints."""
    select_persona(client, "persona_data_steward")
    proposed = client.post(
        "/api/registry/proposals",
        json={
            "source_system_id": source_system_id,
            "dataset_key": dataset_key,
            "source_record_id": record_id,
        },
    )
    assert proposed.status_code == 200, proposed.text
    decided = client.post(
        "/api/registry/decisions",
        json={
            "source_system_id": source_system_id,
            "source_record_id": record_id,
            "decision": "approve",
            "reason": "the evidence names the same party",
        },
    )
    assert decided.status_code == 200, decided.text


def test_at07_the_view_shows_the_authoritative_value_with_its_provenance(
    client: TestClient, environment: tuple[Settings, FixtureBundle], record_property
) -> None:
    settings, _ = environment
    approve(client, "permitting", "applicant_profiles", "PER-AP-0003")
    response = client.get("/api/registry/entities/party_cedarline/trusted-view")
    assert response.status_code == 200, response.text
    view = response.json()
    fields = {field["attribute_path"]: field for field in view["fields"]}
    name = fields["display_name"]
    assert name["state"] == "authoritative"
    assert name["authority_policy_id"] == "authority_person_identity"
    assert name["source_dataset_key"] == "applicant_profiles"
    assert name["source_record_id"] == "PER-AP-0003"
    assert name["source_snapshot_id"]
    assert name["value"] == "Cedar Line Coffee Roasters"

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            provenance = session.execute(
                select(registry.Provenance).where(
                    registry.Provenance.entity_id == "party_cedarline",
                    registry.Provenance.attribute_path == "display_name",
                )
            ).scalars().all()
            assert len(provenance) == 1
            assert provenance[0].authority_policy_id == "authority_person_identity"
            assert provenance[0].source_snapshot_id == name["source_snapshot_id"]
    finally:
        factory.dispose()
    record_property(
        "evidence",
        {
            "entity_id": "party_cedarline",
            "attribute_path": "display_name",
            "authority_policy_id": name["authority_policy_id"],
            "source_snapshot_id": name["source_snapshot_id"],
            "provenance_rows": 1,
        },
    )


def test_at07_the_view_keeps_the_disagreement_with_another_source(
    client: TestClient,
) -> None:
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/sources/permitting/applications_and_permits/intake",
        json={
            "records": [
                {
                    "source_record_id": "PER-APP-AT07-0001",
                    "source_record_version": "1",
                    "payload": {
                        "application_number": "SYN-APP-AT07-01",
                        "permit_type": "com_ti",
                        "organization_name": "Cedarline Coffee Roasters LLC",
                        "contact_email": "newer@example.invalid",
                        "project_description": "A newer application record.",
                        "valuation": 1000.0,
                        "valuation_cents": 100000,
                        "submitted_site_text": "400 Lantern Row Unit 2, ACME City",
                        "submitted_parcel": "ACME-P-1001",
                    },
                    "source_updated_at": "2026-10-20T08:00:00Z",
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    approve(client, "permitting", "applications_and_permits", "PER-APP-AT07-0001")
    approve(client, "permitting", "applicant_profiles", "PER-AP-0003")

    view = client.get("/api/registry/entities/party_cedarline/trusted-view").json()
    fields = {field["attribute_path"]: field for field in view["fields"]}
    assert fields["display_name"]["value"] == "Cedar Line Coffee Roasters"
    disagreements = {item["attribute_path"]: item for item in view["disagreements"]}
    assert "display_name" in disagreements
    assert disagreements["display_name"]["state"] == "disagreement"
    assert disagreements["display_name"]["value"] == "Cedarline Coffee Roasters LLC"


def test_at07_an_unresolved_authority_raises_a_blocking_issue(
    client: TestClient, environment: tuple[Settings, FixtureBundle], record_property
) -> None:
    settings, _ = environment
    approve(client, "permitting", "applications_and_permits", "PER-APP-SYN-APP-001")
    view = client.get("/api/registry/entities/party_cedarline/trusted-view").json()
    fields = {field["attribute_path"]: field for field in view["fields"]}
    assert fields["contact_email"]["state"] == "disputed"
    assert view["issues"]
    issue_id = view["issues"][0]["issue_id"]
    assert view["issues"][0]["blocking"] is True

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            issue = session.get(change.GovernanceIssue, issue_id)
            assert issue is not None
            assert issue.status == "open"
            assert issue.blocking is True
            assert issue.assigned_actor_id == "persona_data_steward"
            assert issue.responsible_queue_id == "queue_applicants"
            task = session.execute(
                select(change.ReviewTask).where(
                    change.ReviewTask.deduplication_key
                    == "field_authority:party_cedarline:contact_email"
                )
            ).scalar_one()
            assert task.status == "open"
    finally:
        factory.dispose()
    record_property(
        "evidence",
        {
            "entity_id": "party_cedarline",
            "attribute_path": "contact_email",
            "issue_id": issue_id,
            "blocking": True,
        },
    )


def test_at07_a_missing_value_is_never_invented(
    client: TestClient,
) -> None:
    approve(client, "permitting", "applicant_profiles", "PER-AP-0003")
    view = client.get("/api/registry/entities/party_cedarline/trusted-view").json()
    fields = {field["attribute_path"]: field for field in view["fields"]}
    licence = fields["business_license_status"]
    assert licence["state"] == "absent"
    assert licence["value"] is None
    assert licence["reasons"]
