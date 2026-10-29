"""AT11: an actual reviewer action.

A permitted reviewer confirms or changes a recommendation through the
application.  The actor, the time, the reason and the versions are persisted.
A client request that merely supplies a final ruling is refused and records
nothing.
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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at11.db'}",
            "ACME_SECRET_KEY": "at11-actual-reviewer-action-secret",
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


def decision_count(settings: Settings) -> int:
    """Count the recorded decisions."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return session.execute(
                select(func.count())
                .select_from(permit.Decision.__table__)
                .where(permit.Decision.application_id == "app_synth_001")
            ).scalar_one()
    finally:
        factory.dispose()


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


def select_persona(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def test_a_reviewer_records_an_actual_decision(
    client: TestClient, environment: Settings
) -> None:
    approve_links(environment)
    select_persona(client, "persona_permit_reviewer")
    evaluation = client.post("/api/permits/applications/app_synth_001/evaluate")
    assert evaluation.status_code == 200, evaluation.text

    response = client.post(
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
    assert response.status_code == 200, response.text
    decision = response.json()["value"]
    assert decision["decided_by_actor_id"] == "persona_permit_reviewer"
    assert decision["decided_at"]
    assert decision["reason"] == "Fictional demonstration approval."
    assert decision["evaluation_id"] == evaluation.json()["evaluation_id"]
    assert decision["rule_versions"] == {"CT-1": "CT-1@1", "CT-2": "CT-2@1"}
    assert decision["input_versions"]["dependency_versions"]
    assert decision_count(environment) == 1


def test_a_request_that_only_supplies_a_final_ruling_records_nothing(
    client: TestClient, environment: Settings
) -> None:
    approve_links(environment)
    select_persona(client, "persona_permit_reviewer")
    client.post("/api/permits/applications/app_synth_001/evaluate")
    before = decision_count(environment)

    refused = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={"final_ruling": "approved"},
    )
    assert refused.status_code == 422
    assert decision_count(environment) == before


def test_an_unauthorized_actor_records_nothing(
    client: TestClient, environment: Settings
) -> None:
    approve_links(environment)
    select_persona(client, "persona_city_administrator")
    before = decision_count(environment)
    refused = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={"outcome": "approved", "reason": "Administrator attempt."},
    )
    assert refused.status_code == 403
    assert decision_count(environment) == before


def test_a_reviewer_may_change_the_recommendation(
    client: TestClient, environment: Settings
) -> None:
    """A reviewer may deny a case or ask for information."""
    approve_links(environment)
    select_persona(client, "persona_permit_reviewer")
    evaluation = client.post("/api/permits/applications/app_synth_001/evaluate")
    assert evaluation.status_code == 200

    requested = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={
            "outcome": "information_requested",
            "reason": "The occupancy load needs to be confirmed.",
            "expected_application_version": client.get(
                "/api/permits/applications/app_synth_001"
            ).json()["application_version"],
            "expected_evaluation_version": evaluation.json()["version"],
        },
    )
    assert requested.status_code == 200, requested.text
    assert requested.json()["value"]["outcome"] == "information_requested"
    application = client.get("/api/permits/applications/app_synth_001").json()
    assert application["status"] == "needs_information"
