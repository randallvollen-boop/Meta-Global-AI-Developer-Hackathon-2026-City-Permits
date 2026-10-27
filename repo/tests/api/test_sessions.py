"""Session API tests: persona selection, signed cookies and scope."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

EXPECTED_PERSONAS = {"Applicant", "Data Steward", "Permit Reviewer", "City Administrator"}


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'sessions.db'}",
            "ACME_SECRET_KEY": "session-test-secret-value",
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
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_persona_selector_returns_exactly_four_personas(client: TestClient) -> None:
    response = client.get("/api/session/actors")
    assert response.status_code == 200
    payload = response.json()
    labels = {entry["label"] for entry in payload["actors"]}
    assert labels == EXPECTED_PERSONAS
    assert len(payload["actors"]) == 4
    identifiers = {entry["actor_id"] for entry in payload["actors"]}
    assert "service_owner_building_safety" not in identifiers
    assert "service_delegate_steward" not in identifiers
    assert "service_governance_lead" not in identifiers


def test_session_without_a_cookie_is_unauthorized(client: TestClient) -> None:
    response = client.get("/api/session")
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_selecting_a_persona_sets_a_signed_http_only_cookie(client: TestClient) -> None:
    response = client.post(
        "/api/session/select", json={"actor_id": "persona_permit_reviewer"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["actor_id"] == "persona_permit_reviewer"

    header = response.headers["set-cookie"]
    assert "httponly" in header.lower()
    assert "samesite=lax" in header.lower()
    assert "acme_session=" in header

    current = client.get("/api/session")
    assert current.status_code == 200
    assert current.json()["actor_id"] == "persona_permit_reviewer"


def test_a_service_identity_cannot_select_a_session(client: TestClient) -> None:
    response = client.post(
        "/api/session/select", json={"actor_id": "service_owner_building_safety"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_an_unsigned_cookie_is_rejected(client: TestClient) -> None:
    client.cookies.delete("acme_session")
    client.cookies.set("acme_session", "not-a-real-session-id")
    response = client.get("/api/session")
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_a_tampered_signature_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/session/select", json={"actor_id": "persona_applicant"}
    )
    assert response.status_code == 200
    value = client.cookies.get("acme_session")
    assert value is not None
    session_id, _, signature = value.partition(".")
    client.cookies.delete("acme_session")
    client.cookies.set("acme_session", f"{session_id}.{'0' * len(signature)}")
    rejected = client.get("/api/session")
    assert rejected.status_code == 401
    assert rejected.json()["code"] == "authentication_required"


def test_client_supplied_role_fields_do_not_authorize(client: TestClient) -> None:
    response = client.post(
        "/api/session/select",
        json={
            "actor_id": "persona_applicant",
            "role_ids": ["administrator", "permit_reviewer"],
            "permissions": ["permit.decide"],
            "domain_scope": ["permits", "finance"],
        },
    )
    assert response.status_code == 200
    current = client.get("/api/session")
    assert current.status_code == 200
    context = current.json()
    assert context["role_ids"] == ["applicant"]
    assert "finance" not in context["domain_scope"]

    denied = client.post(
        "/api/governance/datasets",
        json={
            "source_system_id": "permitting",
            "dataset_key": "unregistered_feeds",
            "label": "An unregistered feed",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"


def test_revoking_a_session_ends_the_access(client: TestClient) -> None:
    client.post("/api/session/select", json={"actor_id": "persona_applicant"})
    assert client.get("/api/session").status_code == 200
    revoked = client.delete("/api/session")
    assert revoked.status_code == 200
    assert client.get("/api/session").status_code == 401


def test_healthz_reports_the_migration_state_without_a_path(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "current"
    assert payload["schema_revision"] == "0001"
    assert "sqlite" not in response.text
