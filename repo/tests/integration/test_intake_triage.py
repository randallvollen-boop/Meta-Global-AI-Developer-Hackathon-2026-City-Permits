"""Simulated outside intake and the agent triage pipeline.

An intake record is staged through its registered contract, becomes a
Permitting application plus revision plus document version through the
existing services, and is then triaged synchronously by the five agent
steps.  Duplicates are idempotent and agents only propose.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.portal_intake.scenarios import build_scenario
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def environment(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'intake.db'}",
            "ACME_SECRET_KEY": "intake-test-secret-value",
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
def client(environment) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def simulate(client: TestClient, scenario: str) -> list[dict]:
    response = client.post("/api/intake/simulate", json={"scenario": scenario})
    assert response.status_code == 200, response.text
    return response.json()["results"]


def test_intake_portal_is_registered_and_shows_in_governance(client: TestClient) -> None:
    choose(client, "persona_city_administrator")
    body = client.get("/governance").text
    assert "intake_portal" in body
    assert "submitted_applications" in body
    systems = client.get("/api/sources/systems").json()
    ids = {row["source_system_id"] for row in systems["source_systems"]}
    assert "intake_portal" in ids


def test_conforming_rear_fence_is_created_triaged_and_recommended_approve(
    client: TestClient, environment
) -> None:
    choose(client, "persona_data_steward")
    (result,) = simulate(client, "fence-conforming-rear")
    assert result["status"] == "created"
    application_id = result["application_id"]
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            steps = session.execute(
                select(agent_models.AgentStep).where(
                    agent_models.AgentStep.application_id == application_id
                )
            ).scalars().all()
            assert [s.step_name for s in steps] == [
                "intake", "identity", "extraction", "rules", "recommendation",
            ]
            assert all(s.ended_at is not None for s in steps)
            assert all(s.service_identity_id.startswith("service_") for s in steps)
            recommendation = session.execute(
                select(permit.Recommendation).where(
                    permit.Recommendation.application_id == application_id,
                    permit.Recommendation.status == "proposed",
                )
            ).scalar_one()
            assert recommendation.proposed_outcome == "approve"
            assert "DF-2" in (recommendation.rationale or "")
            documents = session.execute(
                select(permit.Document).where(
                    permit.Document.application_id == application_id
                )
            ).scalars().all()
            assert {d.document_type for d in documents} == {"site_plan", "material_spec"}
    finally:
        factory.dispose()
    body = client.get(f"/permits/{application_id}").text
    assert 'data-testid="agent-recommendation"' in body
    assert "Advisory. The Permit Reviewer decides." in body
    assert 'data-testid="agent-steps"' in body


def test_front_fence_recommends_deny_citing_df1(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    (result,) = simulate(client, "fence-front-too-tall")
    body = client.get(f"/permits/{result['application_id']}").text
    assert "deny" in body
    assert "DF-1" in body
    assert "4 ft maximum" in body or "ACME Code §14-305" in body


def test_missing_site_plan_becomes_needs_information(client: TestClient, environment) -> None:
    choose(client, "persona_data_steward")
    (result,) = simulate(client, "fence-missing-site-plan")
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = session.get(permit.Application, result["application_id"])
            assert application.status == "needs_information"
            recommendation = session.execute(
                select(permit.Recommendation).where(
                    permit.Recommendation.application_id == application.id
                )
            ).scalar_one()
            assert recommendation.proposed_outcome == "request_information"
    finally:
        factory.dispose()


def test_duplicate_portal_reference_is_idempotent(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    record = build_scenario("fence-conforming-rear")[0]
    first = client.post("/api/intake/records", json=record.model_dump(mode="json"))
    assert first.status_code == 200, first.text
    second = client.post("/api/intake/records", json=record.model_dump(mode="json"))
    assert second.status_code == 200, second.text
    assert first.json()["status"] == "created"
    assert second.json()["status"] == "duplicate"
    assert first.json()["application_id"] == second.json()["application_id"]


def test_mixed_scenario_creates_about_six(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    results = simulate(client, "mixed")
    assert len(results) == 6
    assert all(r["status"] == "created" for r in results)
