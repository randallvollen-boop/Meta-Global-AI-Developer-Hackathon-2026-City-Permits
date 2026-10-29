"""The reviewer decision of parity phase 3b, through the interface.

An approval with conditions is an ``approved`` decision with a non-empty
conditions list.  The form, the API and the reconfirmation all carry the
conditions, and a denial needs a denial reason code.
"""
# REQUIRES: PER-04, UX-02, SEC-03
# The decision form and the decision API record the conditions of an
# approval, and a decision without a rationale is refused.

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import finance, permit, registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.router import router as permit_router
from acme_city.ui.router import router as ui_router

CONDITIONS = ["The fence may not be higher than 4 ft."]

DECIDED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'p3b-decisions.db'}",
            "ACME_SECRET_KEY": "p3b-decision-test-secret-value",
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
    app = create_app(environment)
    app.include_router(ui_router)
    app.include_router(permit_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
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


def application_version(environment: Settings, application_id: str) -> int:
    """Return the current version of one case."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.get(permit.Application, application_id)
            assert row is not None
            return row.version
    finally:
        factory.dispose()


def token(client: TestClient, path: str) -> str:
    """Return the CSRF token of the session from a screen the persona may open."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, f"no CSRF token on {path}"
    return match.group(1)


def decision_row(environment: Settings, application_id: str) -> permit.Decision:
    """Return the current decision of one case."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.execute(
                select(permit.Decision).where(
                    permit.Decision.application_id == application_id,
                    permit.Decision.status == "current",
                )
            ).scalars().first()
            assert row is not None
            return row
    finally:
        factory.dispose()


def test_the_api_records_the_conditions_of_an_approval(
    client: TestClient, environment: Settings
) -> None:
    choose(client, "persona_permit_reviewer")
    approve_links(environment)
    evaluation = client.post("/api/permits/applications/app_synth_001/evaluate")
    assert evaluation.status_code == 200, evaluation.text
    response = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={
            "outcome": "approved_with_conditions",
            "reason": "Fictional demonstration approval with conditions.",
            "conditions": list(CONDITIONS),
            "expected_application_version": application_version(environment, "app_synth_001"),
            "expected_evaluation_version": evaluation.json()["version"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # The recorded outcome stays "approved"; the conditions are carried.
    assert body["value"]["outcome"] == "approved"
    assert body["value"]["conditions"] == list(CONDITIONS)
    assert decision_row(environment, "app_synth_001").conditions == list(CONDITIONS)


def test_the_api_refuses_an_approval_with_conditions_and_no_condition(
    client: TestClient, environment: Settings
) -> None:
    choose(client, "persona_permit_reviewer")
    approve_links(environment)
    evaluation = client.post("/api/permits/applications/app_synth_001/evaluate")
    assert evaluation.status_code == 200, evaluation.text
    response = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={
            "outcome": "approved_with_conditions",
            "reason": "Fictional demonstration approval with conditions.",
            "conditions": [],
            "expected_application_version": application_version(environment, "app_synth_001"),
            "expected_evaluation_version": evaluation.json()["version"],
        },
    )
    assert response.status_code == 422, response.text
    assert "condition" in response.json()["message"]


def test_the_api_refuses_a_decision_without_a_rationale(
    client: TestClient, environment: Settings
) -> None:
    choose(client, "persona_permit_reviewer")
    approve_links(environment)
    evaluation = client.post("/api/permits/applications/app_synth_001/evaluate")
    assert evaluation.status_code == 200, evaluation.text
    response = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={
            "outcome": "approved",
            "reason": "   ",
            "expected_application_version": application_version(environment, "app_synth_001"),
            "expected_evaluation_version": evaluation.json()["version"],
        },
    )
    assert response.status_code == 422, response.text
    assert "rationale" in response.json()["message"]


def test_the_api_refuses_a_denial_without_a_denial_reason_code(
    client: TestClient, environment: Settings
) -> None:
    choose(client, "persona_permit_reviewer")
    approve_links(environment)
    evaluation = client.post("/api/permits/applications/app_synth_001/evaluate")
    assert evaluation.status_code == 200, evaluation.text
    response = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={
            "outcome": "denied",
            "reason": "The contractor registration has to be renewed.",
            "expected_application_version": application_version(environment, "app_synth_001"),
            "expected_evaluation_version": evaluation.json()["version"],
        },
    )
    assert response.status_code == 422, response.text
    assert "reason code" in response.json()["message"].lower()


def test_the_decision_form_records_the_conditions(
    client: TestClient, environment: Settings
) -> None:
    choose(client, "persona_permit_reviewer")
    approve_links(environment)
    evaluation = client.post("/api/permits/applications/app_synth_001/evaluate")
    assert evaluation.status_code == 200, evaluation.text
    page = client.get("/permits/app_synth_001")
    assert page.status_code == 200, page.text
    assert 'data-testid="decision-form"' in page.text
    csrf = token(client, "/permits/app_synth_001")
    response = client.post(
        "/ui/actions/permit.decide",
        data={
            "csrf_token": csrf,
            "action_id": "permit.decide",
            "next": "/permits/app_synth_001",
            "application_id": "app_synth_001",
            "outcome": "approved_with_conditions",
            "conditions": "\n".join(CONDITIONS),
            "reason": "Fictional demonstration approval with conditions.",
            "expected_application_version": str(application_version(environment, "app_synth_001")),
            "expected_application_version": str(application_version(environment, "app_synth_001")),
            "expected_evaluation_version": str(evaluation.json()["version"]),
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"
    decision = decision_row(environment, "app_synth_001")
    assert decision.outcome == "approved"
    assert decision.conditions == list(CONDITIONS)


def test_the_decision_form_refuses_an_approval_with_conditions_and_no_condition(
    client: TestClient, environment: Settings
) -> None:
    choose(client, "persona_permit_reviewer")
    approve_links(environment)
    evaluation = client.post("/api/permits/applications/app_synth_001/evaluate")
    assert evaluation.status_code == 200, evaluation.text
    csrf = token(client, "/permits/app_synth_001")
    response = client.post(
        "/ui/actions/permit.decide",
        data={
            "csrf_token": csrf,
            "action_id": "permit.decide",
            "next": "/permits/app_synth_001",
            "application_id": "app_synth_001",
            "outcome": "approved_with_conditions",
            "conditions": "   ",
            "reason": "Fictional demonstration approval with conditions.",
            "expected_application_version": str(application_version(environment, "app_synth_001")),
            "expected_application_version": str(application_version(environment, "app_synth_001")),
            "expected_evaluation_version": str(evaluation.json()["version"]),
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert "condition" in response.json()["message"]


def test_the_decision_form_is_not_offered_to_a_persona_without_the_grant(
    client: TestClient,
) -> None:
    choose(client, "persona_data_steward")
    page = client.get("/permits/app_synth_001")
    assert page.status_code == 200, page.text
    assert 'data-testid="decision-form"' not in page.text
