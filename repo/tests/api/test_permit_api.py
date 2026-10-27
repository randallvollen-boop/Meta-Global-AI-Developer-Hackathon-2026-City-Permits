"""Permit API tests: authorization boundaries and zero business mutations.

The application factory is used as it is; the permit, rules and finance
routers are mounted on it exactly as the integration mounts them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.finance.router import router as finance_router
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.router import router as permit_router
from acme_city.rules.router import router as rules_router

BUSINESS_TABLES = ("applications", "application_revisions", "evaluations", "decisions")


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'permit-api.db'}",
            "ACME_SECRET_KEY": "permit-api-test-secret-value",
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


@pytest.fixture()
def client(environment: Settings) -> TestClient:
    """Return a client with the permit, rules and finance routers mounted."""
    app = create_app(environment)
    app.include_router(permit_router)
    app.include_router(rules_router)
    app.include_router(finance_router)
    with TestClient(app) as test_client:
        yield test_client


def row_counts(settings: Settings) -> dict[str, int]:
    """Count the business rows that a refused action must not change."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return {
                name: session.execute(
                    select(func.count()).select_from(permit.Application.__table__)
                    if name == "applications"
                    else select(func.count()).select_from(permit.ApplicationRevision.__table__)
                    if name == "application_revisions"
                    else select(func.count()).select_from(permit.Evaluation.__table__)
                    if name == "evaluations"
                    else select(func.count()).select_from(permit.Decision.__table__)
                ).scalar_one()
                for name in BUSINESS_TABLES
            }
    finally:
        factory.dispose()


def select_persona(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def test_the_permit_endpoints_require_a_session(client: TestClient) -> None:
    assert client.get("/api/permits/applications").status_code == 401
    assert client.get("/api/permits/applications/app_synth_001").status_code == 401
    assert (
        client.post(
            "/api/permits/applications/app_synth_001/evaluate",
        ).status_code
        == 401
    )


def test_an_applicant_may_not_evaluate_an_application(
    client: TestClient, environment: Settings
) -> None:
    before = row_counts(environment)
    select_persona(client, "persona_applicant")
    response = client.post("/api/permits/applications/app_synth_001/evaluate")
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    assert row_counts(environment) == before


def test_the_city_administrator_may_not_decide_an_application(
    client: TestClient, environment: Settings
) -> None:
    before = row_counts(environment)
    select_persona(client, "persona_city_administrator")
    response = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={"outcome": "approved", "reason": "Administrator attempt."},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    assert row_counts(environment) == before


def test_a_client_role_field_never_authorizes_a_decision(
    client: TestClient, environment: Settings
) -> None:
    """A body that claims authority changes nothing."""
    before = row_counts(environment)
    select_persona(client, "persona_applicant")
    response = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={
            "outcome": "approved",
            "reason": "Claimed authority.",
            "role": "permit_reviewer",
            "actor_id": "persona_permit_reviewer",
        },
    )
    assert response.status_code in (403, 422)
    assert row_counts(environment) == before


def test_a_ruling_without_a_transition_is_refused(
    client: TestClient, environment: Settings
) -> None:
    """A final ruling is not a decision."""
    before = row_counts(environment)
    select_persona(client, "persona_permit_reviewer")
    response = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={"final_ruling": "approved"},
    )
    assert response.status_code == 422
    assert row_counts(environment) == before


def test_an_applicant_sees_only_the_applications_in_scope(
    client: TestClient,
) -> None:
    select_persona(client, "persona_applicant")
    response = client.get("/api/permits/applications")
    assert response.status_code == 200
    numbers = {
        item["source_application_number"]
        for item in response.json()["applications"]
    }
    assert "SYN-APP-005" in numbers
    assert "SYN-APP-001" not in numbers


def test_a_submission_through_the_api_records_a_revision(
    client: TestClient,
) -> None:
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/permits/applications",
        json={
            "permit_type_key": "com_ti",
            "applicant_party_id": "party_cedarline",
            "facts": {
                "project_description": "A fictional interior tenant improvement.",
                "valuation": 50000.0,
                "valuation_cents": 5000000,
                "occupancy_load": 42,
                "contractor_license": "CR-2026-00188",
                "applicant_role": "business",
                "submitted_parcel": "ACME-P-1001",
                "submitted_site_text": "400 Lantern Row, Suite 2, ACME City",
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision_number"] == 1
    assert body["status"] == "submitted"
    assert body["initial_submitted_at"] is not None


def test_the_evaluation_endpoint_returns_the_versions_it_used(
    client: TestClient,
) -> None:
    select_persona(client, "persona_permit_reviewer")
    response = client.post("/api/permits/applications/app_synth_001/evaluate")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rule_versions"] == {"CT-1": "CT-1@1", "CT-2": "CT-2@1"}
    assert body["date_basis"].startswith("initial_submitted_at@")
    assert body["inputs"]["valuation_cents"] == 5000000
    assert body["outcome"] == "pass"


def test_a_document_version_is_stored_with_its_bytes(client: TestClient) -> None:
    """A stored document carries the bytes that were received, not a label."""
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/permits/applications/app_synth_001/documents",
        data={"document_type": "construction_plans"},
        files={"file": ("plans.pdf", b"%PDF-1.4 fictional demonstration bytes", "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document_type"] == "construction_plans"
    assert body["version"] == 1
    assert body["byte_length"] == 38
    assert body["content_hash"]
    assert body["fictional_demo"] is True

    listed = client.get("/api/permits/applications/app_synth_001/documents")
    assert listed.status_code == 200
    assert [item["document_id"] for item in listed.json()["documents"]] == [
        body["document_id"]
    ]

    content = client.get(f"/api/permits/documents/{body['document_id']}/content")
    assert content.status_code == 200
    assert content.content == b"%PDF-1.4 fictional demonstration bytes"


def test_an_unsupported_media_type_is_refused(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/permits/applications/app_synth_001/documents",
        data={"document_type": "construction_plans"},
        files={"file": ("plans.exe", b"fictional demonstration bytes", "application/x-msdownload")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


def test_an_empty_document_is_refused(client: TestClient) -> None:
    """A label without bytes never becomes a document version."""
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/permits/applications/app_synth_001/documents",
        data={"document_type": "construction_plans"},
        files={"file": ("plans.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 422


def test_only_a_steward_may_apply_a_change_impact(client: TestClient) -> None:
    """A source correction is a stewardship act, not a reviewer action."""
    select_persona(client, "persona_permit_reviewer")
    refused = client.post(
        "/api/permits/impacts",
        json={"kind": "rule", "identifier": "CT-2", "reason": "Reviewer attempt."},
    )
    assert refused.status_code == 403
    assert refused.json()["code"] == "permission_denied"

    select_persona(client, "persona_data_steward")
    accepted = client.post(
        "/api/permits/impacts",
        json={
            "kind": "rule",
            "identifier": "CT-2",
            "reason": "A new version of the large tenant improvement rule was published.",
        },
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["dependency_key"] == "rule:CT-2"
    assert body["affected"]


def test_a_stale_expected_version_returns_a_conflict(client: TestClient) -> None:
    select_persona(client, "persona_permit_reviewer")
    response = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={
            "outcome": "approved",
            "reason": "Stale expectation.",
            "expected_application_version": 99,
        },
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "version_conflict"
    assert body["expected_version"] == 99
    assert "current_version" in body
