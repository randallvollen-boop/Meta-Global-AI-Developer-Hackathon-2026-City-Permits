"""Issuance API tests: a separate authorized action that is idempotent.

A simulated timeout after the transaction commits leaves the caller without
an answer.  The identical retry returns the original permit, number and
artifact, and a reused command key with other facts is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.finance.router import router as finance_router
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import finance, permit, registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.router import router as permit_router
from acme_city.rules.router import router as rules_router

DECIDED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'issuance-api.db'}",
            "ACME_SECRET_KEY": "issuance-api-test-secret-value",
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


def select_persona(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def approve_links(environment: Settings) -> None:
    """Record the canonical links a steward would have approved."""
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            for party_id in ("party_cedarline", "party_ironvale"):
                session.add(
                    registry.Crosswalk(
                        id=f"crosswalk_{party_id}",
                        entity_id=party_id,
                        entity_type="party",
                        source_system_id="permitting",
                        source_dataset_key="applicant_profiles",
                        source_record_id=f"PER-{party_id}",
                        link_status="approved",
                        decision="Approved by the data steward.",
                        decision_actor_id="persona_data_steward",
                        decided_at=DECIDED_AT,
                    )
                )
            session.add(
                finance.FinanceAccountLink(
                    id="faclink_legacy",
                    account_id="facct_cedarline_legacy",
                    party_id="party_cedarline",
                    link_status="approved",
                    decided_by_actor_id="persona_data_steward",
                    decided_at=DECIDED_AT,
                )
            )
    finally:
        factory.dispose()


def permit_count(settings: Settings) -> int:
    """Count the permits issued for the D01 case."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return session.execute(
                select(func.count())
                .select_from(permit.Permit.__table__)
                .where(permit.Permit.application_id == "app_synth_001")
            ).scalar_one()
    finally:
        factory.dispose()


def run_the_chain(client: TestClient, environment: Settings) -> dict:
    """Evaluate, approve, assess, allocate and reconcile through the API."""
    approve_links(environment)
    select_persona(client, "persona_permit_reviewer")
    evaluation = client.post("/api/permits/applications/app_synth_001/evaluate")
    assert evaluation.status_code == 200, evaluation.text
    decision = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={
            "outcome": "approved",
            "reason": "Fictional demonstration approval.",
            "expected_application_version": client.get(
                "/api/permits/applications/app_synth_001"
            ).json()["application_version"],
            "expected_evaluation_version": evaluation.json()["version"],
        },
    )
    assert decision.status_code == 200, decision.text
    select_persona(client, "persona_city_administrator")
    assessment = client.post(
        "/api/finance/assessments", json={"application_id": "app_synth_001"}
    )
    assert assessment.status_code == 200, assessment.text
    allocation = client.post(
        "/api/finance/allocations",
        json={
            "payment_id": "payment_d01_settled",
            "assessment_id": assessment.json()["assessment_id"],
            "amount": "150.00",
            "idempotency_key": "alloc:test:issuance-api",
        },
    )
    assert allocation.status_code == 200, allocation.text
    return {
        "decision_id": decision.json()["value"]["decision_id"],
        "application_version": decision.json()["value"]["input_versions"][
            "application_version"
        ],
    }


def test_the_issuance_endpoint_requires_a_session(client: TestClient) -> None:
    response = client.post(
        "/api/permits/applications/app_synth_001/issue",
        json={
            "decision_id": "decision_d07",
            "expected_application_version": 1,
            "expected_decision_version": 1,
            "command_key": "issue:test:api",
        },
    )
    assert response.status_code == 401


def test_the_city_administrator_may_not_issue(
    client: TestClient, environment: Settings
) -> None:
    state = run_the_chain(client, environment)
    before = permit_count(environment)
    select_persona(client, "persona_city_administrator")
    response = client.post(
        "/api/permits/applications/app_synth_001/issue",
        json={
            "decision_id": state["decision_id"],
            "expected_application_version": state["application_version"] + 1,
            "expected_decision_version": 1,
            "command_key": "issue:test:api-admin",
        },
    )
    assert response.status_code == 403
    assert permit_count(environment) == before


def test_an_identical_retry_returns_the_original_permit(
    client: TestClient, environment: Settings
) -> None:
    """A timeout after the commit leaves the permit in place."""
    state = run_the_chain(client, environment)
    select_persona(client, "persona_permit_reviewer")
    application = client.get("/api/permits/applications/app_synth_001").json()
    payload = {
        "decision_id": state["decision_id"],
        "expected_application_version": application["application_version"],
        "expected_decision_version": 1,
        "command_key": "issue:test:api-retry",
    }
    first = client.post("/api/permits/applications/app_synth_001/issue", json=payload)
    assert first.status_code == 200, first.text
    body = first.json()["value"]
    assert body["permit_number"].startswith("ACME-")
    assert body["artifact_hash"]

    # The caller never saw the answer: the identical retry is harmless.
    second = client.post("/api/permits/applications/app_synth_001/issue", json=payload)
    assert second.status_code == 200, second.text
    retry = second.json()["value"]
    assert retry["permit_id"] == body["permit_id"]
    assert retry["permit_number"] == body["permit_number"]
    assert retry["artifact_hash"] == body["artifact_hash"]
    assert permit_count(environment) == 1


def test_a_reused_command_key_with_other_facts_is_refused(
    client: TestClient, environment: Settings
) -> None:
    state = run_the_chain(client, environment)
    select_persona(client, "persona_permit_reviewer")
    application = client.get("/api/permits/applications/app_synth_001").json()
    payload = {
        "decision_id": state["decision_id"],
        "expected_application_version": application["application_version"],
        "expected_decision_version": 1,
        "command_key": "issue:test:api-conflict",
    }
    assert (
        client.post("/api/permits/applications/app_synth_001/issue", json=payload).status_code
        == 200
    )
    payload["expected_application_version"] = payload["expected_application_version"] + 1
    refused = client.post("/api/permits/applications/app_synth_001/issue", json=payload)
    assert refused.status_code == 409
    assert refused.json()["code"] == "issuance_key_reused"
    assert permit_count(environment) == 1


def test_a_stale_expected_version_returns_a_conflict(
    client: TestClient, environment: Settings
) -> None:
    state = run_the_chain(client, environment)
    select_persona(client, "persona_permit_reviewer")
    refused = client.post(
        "/api/permits/applications/app_synth_001/issue",
        json={
            "decision_id": state["decision_id"],
            "expected_application_version": 99,
            "expected_decision_version": 1,
            "command_key": "issue:test:api-stale",
        },
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "version_conflict"
    assert permit_count(environment) == 0
