"""Change API tests: requests, transitions, conflicts and the impact preview."""

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
from acme_city.persistence.models import change
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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'changes-api.db'}",
            "ACME_SECRET_KEY": "changes-api-secret-value",
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
    app.include_router(changes_router)
    with TestClient(app) as test_client:
        yield test_client


def select_persona(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def request_change(client: TestClient, target_id: str = "SYN-APP-005") -> dict:
    """Request a correction of an application."""
    response = client.post(
        "/api/changes",
        json={
            "target_type": "application",
            "target_id": target_id,
            "title": "Fictional correction of a submitted description",
            "reason": "the submitted description names the wrong counter",
            "change_kind": "factual",
            "proposed_value": {"project_description": "A corrected fictional description."},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def transition(client: TestClient, change_case_id: str, to_status: str, **extra) -> dict:
    """Move a change case to the next permitted state."""
    payload = {"to_status": to_status}
    payload.update(extra)
    response = client.post(f"/api/changes/{change_case_id}/transition", json=payload)
    assert response.status_code in {200, 403, 409, 422}, response.text
    return response.json()


def test_the_change_endpoints_require_a_session(client: TestClient) -> None:
    assert client.get("/api/changes").status_code == 401
    response = client.post(
        "/api/changes",
        json={
            "target_type": "application",
            "target_id": "SYN-APP-005",
            "title": "A fictional correction",
            "reason": "a fictional reason",
        },
    )
    assert response.status_code == 401


def test_an_applicant_may_request_a_correction_for_their_own_case(
    client: TestClient,
) -> None:
    select_persona(client, "persona_applicant")
    payload = request_change(client)
    assert payload["status"] == "requested"
    assert payload["requester_actor_id"] == "persona_applicant"
    assert payload["destination"] == "Permitting application workspace"
    assert payload["assignee_actor_id"] == "persona_data_steward"
    assert payload["allowed_transitions"] == ["in_review", "rejected"]


def test_an_applicant_may_not_request_a_correction_for_another_case(
    client: TestClient,
) -> None:
    select_persona(client, "persona_applicant")
    response = client.post(
        "/api/changes",
        json={
            "target_type": "application",
            "target_id": "SYN-APP-001",
            "title": "A fictional correction of another case",
            "reason": "a fictional reason",
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_the_steward_reviews_and_approves_a_request_of_another_actor(
    client: TestClient,
) -> None:
    select_persona(client, "persona_applicant")
    payload = request_change(client)
    change_case_id = payload["change_case_id"]

    select_persona(client, "persona_data_steward")
    reviewed = transition(client, change_case_id, "in_review")
    assert reviewed["value"]["status"] == "in_review"
    waiting = transition(client, change_case_id, "awaiting_approval")
    assert waiting["value"]["status"] == "awaiting_approval"
    approved = transition(client, change_case_id, "approved")
    assert approved["value"]["status"] == "approved"
    assert approved["value"]["approver_actor_id"] == "persona_data_steward"


def test_a_steward_may_not_approve_their_own_request(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/changes",
        json={
            "target_type": "source_record",
            "target_id": "gis/address_register/GIS-AD-0400",
            "title": "A fictional correction of an official address",
            "reason": "the postcode of the official address is wrong",
            "proposed_value": {"address_id": "GIS-AD-0400"},
        },
    )
    assert response.status_code == 200, response.text
    change_case_id = response.json()["change_case_id"]
    transition(client, change_case_id, "in_review")
    transition(client, change_case_id, "awaiting_approval")
    approved = transition(client, change_case_id, "approved")
    assert approved["code"] == "permission_denied"
    assert "may not approve" in approved["message"]

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            case = session.get(change.ChangeCase, change_case_id)
            assert case.status == "awaiting_approval"
            assert case.approver_actor_id is None
    finally:
        factory.dispose()


def test_a_stale_expected_version_returns_a_conflict(client: TestClient) -> None:
    select_persona(client, "persona_applicant")
    payload = request_change(client)
    change_case_id = payload["change_case_id"]
    select_persona(client, "persona_data_steward")
    stale = transition(client, change_case_id, "in_review", expected_version=99)
    assert stale["code"] == "version_conflict"
    assert stale["current_version"] == 1
    assert stale["expected_version"] == 99


def test_an_unknown_transition_is_refused(client: TestClient) -> None:
    select_persona(client, "persona_applicant")
    payload = request_change(client)
    change_case_id = payload["change_case_id"]
    select_persona(client, "persona_data_steward")
    refused = transition(client, change_case_id, "published")
    assert refused["code"] == "validation_failed"


def test_the_impact_preview_names_the_affected_records(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/changes/impact/preview",
        json={"target_type": "canonical_entity", "target_id": "party_cedarline"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "app_synth_001" in payload["applications"]
    assert payload["total_affected"] >= 1
    assert any("recheck" in item for item in payload["rechecks"])


def test_the_dispatch_endpoint_needs_the_transition_permission(
    client: TestClient,
) -> None:
    select_persona(client, "persona_applicant")
    refused = client.post("/api/changes/dispatch")
    assert refused.status_code == 403
    select_persona(client, "persona_data_steward")
    allowed = client.post("/api/changes/dispatch")
    assert allowed.status_code == 200
    assert allowed.json()["dispatched"] == 0


def test_the_change_cases_are_listed_with_their_state(client: TestClient) -> None:
    select_persona(client, "persona_applicant")
    payload = request_change(client)
    response = client.get("/api/changes", params={"status": "requested"})
    assert response.status_code == 200
    identifiers = [row["change_case_id"] for row in response.json()["change_cases"]]
    assert payload["change_case_id"] in identifiers


def test_a_missing_change_case_is_reported_as_not_found(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    response = client.get("/api/changes/case_that_does_not_exist")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
