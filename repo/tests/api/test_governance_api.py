"""Governance API tests: authorization boundaries and zero business mutations."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import governance
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

BUSINESS_TABLES = ("source_contracts", "assignments", "authority_policies", "actors")


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'governance-api.db'}",
            "ACME_SECRET_KEY": "governance-api-secret-value",
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
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def business_row_counts(settings: Settings) -> dict[str, int]:
    """Count the business rows that a denied action must not change."""
    from acme_city.persistence.base import Base

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return {
                name: session.execute(
                    select(func.count()).select_from(Base.metadata.tables[name])
                ).scalar_one()
                for name in BUSINESS_TABLES
            }
    finally:
        factory.dispose()


def select_persona(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def test_governance_endpoints_require_a_session(client: TestClient) -> None:
    assert client.get("/api/governance/datasets").status_code == 401
    assert client.get("/api/governance/assignments").status_code == 401
    assert (
        client.post(
            "/api/governance/datasets",
            json={"source_system_id": "permitting", "dataset_key": "x", "label": "x"},
        ).status_code
        == 401
    )


def test_an_applicant_cannot_register_a_dataset(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    before = business_row_counts(settings)
    select_persona(client, "persona_applicant")
    response = client.post(
        "/api/governance/datasets",
        json={
            "source_system_id": "permitting",
            "dataset_key": "unregistered_feeds",
            "label": "An unregistered feed",
            "domain_id": "permits",
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    after = business_row_counts(settings)
    assert after == before


def test_the_city_administrator_may_register_a_dataset(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    before = business_row_counts(settings)
    select_persona(client, "persona_city_administrator")
    response = client.post(
        "/api/governance/datasets",
        json={
            "source_system_id": "permitting",
            "dataset_key": "unregistered_feeds",
            "label": "An unregistered feed",
            "domain_id": "permits",
            "accountable_owner_actor_id": "service_owner_building_safety",
            "steward_queue_id": "queue_permits",
            "system_custodian_actor_id": "service_custodian_permitting",
            "authority_policy_id": "authority_application_facts",
            "correction_route": "Permitting application workspace",
            "schema_version": "1.0",
            "business_key_fields": ["application_number"],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["value"]["registration_state"] == "complete"
    assert payload["value"]["publishable"] is True
    assert payload["audit_event_id"]
    after = business_row_counts(settings)
    assert after["source_contracts"] == before["source_contracts"] + 1


def test_an_incomplete_registration_cannot_publish(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    select_persona(client, "persona_city_administrator")
    registered = client.post(
        "/api/governance/datasets",
        json={
            "source_system_id": "permitting",
            "dataset_key": "unregistered_feeds",
            "label": "An unregistered feed",
        },
    )
    assert registered.status_code == 200
    assert registered.json()["value"]["publishable"] is False

    published = client.post("/api/governance/datasets/unregistered_feeds/publish")
    assert published.status_code == 409
    payload = published.json()
    assert payload["code"] == "incomplete_registration"
    assert "accountable_owner" in payload["missing_bindings"]


def test_an_out_of_scope_direct_url_is_refused(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    before = business_row_counts(settings)
    select_persona(client, "persona_city_administrator")
    response = client.post(
        "/api/governance/assignments/reassign",
        json={
            "domain_id": "registry_links",
            "responsibility": "steward",
            "new_actor_id": "service_delegate_steward",
            "reason": "fictional demonstration of an out-of-scope direct URL",
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    after = business_row_counts(settings)
    assert after == before


def test_reassignment_is_visible_and_keeps_the_prior_attribution(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    select_persona(client, "persona_city_administrator")
    before = client.get("/api/governance/assignments?domain_id=applicants").json()
    steward_before = next(
        entry for entry in before["assignments"] if entry["responsibility"] == "steward"
    )
    assert steward_before["actor_id"] == "persona_data_steward"

    response = client.post(
        "/api/governance/assignments/reassign",
        json={
            "domain_id": "applicants",
            "responsibility": "steward",
            "new_actor_id": "service_delegate_steward",
            "reason": "fictional demonstration reassignment",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["value"]["actor_id"] == "service_delegate_steward"
    assert payload["value"]["supersedes_assignment_id"] == steward_before["assignment_id"]

    after = client.get("/api/governance/assignments?domain_id=applicants").json()
    steward_after = next(
        entry for entry in after["assignments"] if entry["responsibility"] == "steward"
    )
    assert steward_after["actor_id"] == "service_delegate_steward"
    assert steward_after["assignment_id"] != steward_before["assignment_id"]


def test_deactivating_a_steward_with_active_work_is_a_conflict(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    factory = SessionFactory(settings.database_url)
    try:
        from acme_city.persistence.models import change

        with transaction(factory) as session:
            session.add(
                change.ChangeCase(
                    id="api_case_for_steward",
                    correlation_id="corr_api_case_for_steward",
                    target_type="source_record",
                    target_id="PER-AP-0003",
                    change_kind="factual",
                    title="Fictional open case",
                    requester_actor_id="persona_applicant",
                    assignee_actor_id="persona_data_steward",
                    status="in_review",
                )
            )
    finally:
        factory.dispose()

    select_persona(client, "persona_city_administrator")
    response = client.post(
        "/api/governance/actors/persona_data_steward/deactivate",
        json={"actor_id": "persona_data_steward", "reason": "fictional demonstration deactivation"},
    )
    assert response.status_code == 409
    payload = response.json()
    assert payload["code"] == "active_work_conflict"
    assert "api_case_for_steward" in payload["active_work"]

    with factory() as session:
        assert session.get(governance.Actor, "persona_data_steward").active is True


def test_deactivation_with_reassignment_succeeds(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    select_persona(client, "persona_city_administrator")
    response = client.post(
        "/api/governance/actors/persona_data_steward/deactivate",
        json={
            "actor_id": "persona_data_steward",
            "reason": "fictional demonstration deactivation",
            "reassign_domain_id": "applicants",
            "reassign_to_actor_id": "service_delegate_steward",
        },
    )
    assert response.status_code == 200, response.text
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            assert session.get(governance.Actor, "persona_data_steward").active is False
    finally:
        factory.dispose()


def test_authority_preview_and_publication(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    select_persona(client, "persona_city_administrator")
    preview = client.post(
        "/api/governance/authority/preview",
        json={
            "policy_id": "authority_application_facts",
            "field_group": "Submitted project description and valuation",
            "domain_id": "permits",
            "authoritative_source_system_id": "permitting",
            "authoritative_dataset_key": "application_revisions",
            "change_destination": "Permitting application revision",
            "user_action": "Permits > Application > Submit correction",
            "requires_source_ack": True,
            "decision_relevant": True,
        },
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert "application_revisions" in payload["impacted_datasets"]
    assert payload["current_policy_version"] >= 1

    published = client.post(
        "/api/governance/authority/publish",
        json={
            "policy_id": "authority_application_facts",
            "approver_actor_id": "service_governance_lead",
            "expected_version": payload["current_policy_version"],
            "reason": "fictional demonstration publication",
        },
    )
    assert published.status_code == 200, published.text
    assert published.json()["value"]["status"] == "published"


def test_an_author_may_not_approve_its_own_authority_policy(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    select_persona(client, "persona_city_administrator")
    response = client.post(
        "/api/governance/authority/publish",
        json={
            "policy_id": "authority_application_facts",
            "approver_actor_id": "persona_city_administrator",
            "expected_version": 1,
            "reason": "fictional demonstration self approval",
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
