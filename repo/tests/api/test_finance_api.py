"""Finance API tests: the governed financial boundary.

Amounts cross the boundary as decimal strings, the currency is explicit and
every financial action is a separate authorized Finance action.
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
from acme_city.persistence.models import finance
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.router import router as permit_router
from acme_city.rules.router import router as rules_router


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'finance-api.db'}",
            "ACME_SECRET_KEY": "finance-api-test-secret-value",
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


def assessment_count(settings: Settings) -> int:
    """Count the stored assessments."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return session.execute(
                select(func.count()).select_from(finance.Assessment.__table__)
            ).scalar_one()
    finally:
        factory.dispose()


def allocation_count(settings: Settings) -> int:
    """Count the stored allocations."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return session.execute(
                select(func.count()).select_from(finance.Allocation.__table__)
            ).scalar_one()
    finally:
        factory.dispose()


def select_persona(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def test_the_finance_endpoints_require_a_session(client: TestClient) -> None:
    assert client.post("/api/finance/assessments", json={"application_id": "app_synth_001"}).status_code == 401
    assert (
        client.post(
            "/api/finance/allocations",
            json={
                "payment_id": "payment_d01_settled",
                "assessment_id": "assess_d07_v1",
                "amount": "150.00",
                "idempotency_key": "alloc:test:api",
            },
        ).status_code
        == 401
    )


def test_a_reviewer_may_not_assess(client: TestClient, environment: Settings) -> None:
    before = assessment_count(environment)
    select_persona(client, "persona_permit_reviewer")
    response = client.post(
        "/api/finance/assessments", json={"application_id": "app_synth_001"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    assert assessment_count(environment) == before


def test_the_assessment_endpoint_returns_the_itemized_lines(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.post(
        "/api/finance/assessments", json={"application_id": "app_synth_001"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assessed_total"] == "150.00"
    assert body["assessed_total_cents"] == 15000
    assert body["currency"] == "USD"
    codes = [line["fee_code"] for line in body["lines"]]
    assert codes == ["COM_REVIEW_FIXED", "COM_REVIEW_VARIABLE"]


def test_a_replayed_payment_returns_the_same_receipt(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    payload = {
        "source_transaction_id": "ERP-TXN-2026-91001",
        "source_event_id": "ERP-EVT-2026-91001-1",
        "event_type": "settled",
        "amount": "150.00",
        "currency": "USD",
        "payer_account_id": "facct_cedarline_legacy",
    }
    first = client.post("/api/finance/payments", json=payload)
    second = client.post("/api/finance/payments", json=payload)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["payment_id"] == second.json()["payment_id"]
    assert len(second.json()["events"]) == 1


def test_a_reused_event_with_other_facts_is_a_conflict(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    payload = {
        "source_transaction_id": "ERP-TXN-2026-91002",
        "source_event_id": "ERP-EVT-2026-91002-1",
        "event_type": "settled",
        "amount": "150.00",
        "payer_account_id": "facct_cedarline_legacy",
    }
    assert client.post("/api/finance/payments", json=payload).status_code == 200
    payload["amount"] = "200.00"
    refused = client.post("/api/finance/payments", json=payload)
    assert refused.status_code == 409
    assert refused.json()["code"] == "payment_event_conflict"


def test_an_unlinked_payer_is_refused(client: TestClient, environment: Settings) -> None:
    select_persona(client, "persona_city_administrator")
    assessment = client.post(
        "/api/finance/assessments", json={"application_id": "app_synth_001"}
    )
    assert assessment.status_code == 200
    before = allocation_count(environment)
    refused = client.post(
        "/api/finance/allocations",
        json={
            "payment_id": "payment_d01_settled",
            "assessment_id": assessment.json()["assessment_id"],
            "amount": "150.00",
            "idempotency_key": "alloc:test:api-unlinked",
        },
    )
    assert refused.status_code == 422
    assert allocation_count(environment) == before


def test_the_reconciliation_endpoint_reports_the_position(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    assessment = client.post(
        "/api/finance/assessments", json={"application_id": "app_synth_001"}
    )
    assert assessment.status_code == 200
    response = client.post(
        "/api/finance/reconciliations",
        json={"assessment_id": assessment.json()["assessment_id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "unpaid"
    assert body["assessed_total"] == "150.00"
    assert body["settled_allocated"] == "0.00"
    assert body["balance"] == "150.00"
