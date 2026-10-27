"""USE_CASE_FENCE: the documented manual fence walkthrough, automated.

Follows docs/operations/USE_CASE_FENCE.md step by step through the real HTTP
surface (the same governed endpoints and UI actions the browser posts to):
administrator simulation of the two fence scenarios, triage, steward link
approval, reviewer decisions, then fee assessment, payment, allocation,
reconciliation and issuance for the approved case.  Amounts are always read
from API responses, never assumed.
"""

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
from acme_city.persistence.models import permit, registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

DECIDED_AT = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


@pytest.fixture()
def environment(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'fence.db'}",
            "ACME_SECRET_KEY": "fence-use-case-secret-value",
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


def simulate(client: TestClient, scenario: str) -> dict:
    response = client.post("/api/intake/simulate", json={"scenario": scenario})
    assert response.status_code == 200, response.text
    (result,) = response.json()["results"]
    assert result["status"] == "created", result
    return result


def csrf(client: TestClient, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def act(client: TestClient, action_id: str, fields: dict, next_path: str) -> dict:
    response = client.post(
        f"/ui/actions/{action_id}",
        data={
            "csrf_token": csrf(client, next_path),
            "action_id": action_id,
            "next": next_path,
            **fields,
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text
    return response.json()


def application_row(settings, application_id: str):
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            row = session.get(permit.Application, application_id)
            return {
                "version": row.version,
                "status": row.status,
                "facts": dict(row.submitted_facts or {}),
                "number": row.source_application_number,
            }
    finally:
        factory.dispose()


def approve_applicant_link(settings, application_id: str) -> None:
    """Record the steward-approved canonical link issuance requires.

    This is the recorded outcome of the Steward review decision in the
    walkthrough (compare tests/api/test_issuance_api.py): the identity agent
    proposed, the steward approved.  It is written as a crosswalk row because
    the registry decision endpoint needs a proposed crosswalk for the exact
    source record, which the seeded D01 flow provides and a brand-new intake
    party link reaches through the same table.
    """
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(permit.Application, application_id)
            party_id = application.applicant_party_id
            assert party_id, "intake should attach the named applicant party"
            session.add(
                registry.Crosswalk(
                    id=f"crosswalk_fence_{application_id}",
                    entity_id=party_id,
                    entity_type="party",
                    source_system_id="intake_portal",
                    source_dataset_key="submitted_applications",
                    source_record_id=str((application.submitted_facts or {}).get("portal_reference")),
                    link_status="approved",
                    decision="Approved by the data steward in the fence walkthrough.",
                    decision_actor_id="persona_data_steward",
                    decided_at=DECIDED_AT,
                )
            )
    finally:
        factory.dispose()


def test_use_case_fence(client: TestClient, environment) -> None:
    # 1-2. Administrator simulates both fence scenarios (USE_CASE step 2).
    choose(client, "persona_city_administrator")
    assert 'data-action-id="intake.simulate"' in client.get("/governance").text
    front = simulate(client, "fence-front-too-tall")
    rear = simulate(client, "fence-conforming-rear")
    front_id, rear_id = front["application_id"], rear["application_id"]

    # 3. Triage recorded; recommendations exactly as the document states.
    front_body = client.get(f"/permits/{front_id}").text
    rear_body = client.get(f"/permits/{rear_id}").text
    for body in (front_body, rear_body):
        assert 'data-testid="agent-steps"' in body
        for step in ("intake", "identity", "extraction", "rules", "recommendation"):
            assert f'data-step-name="{step}"' in body
        assert 'data-testid="agent-recommendation"' in body
        assert "Advisory. The Permit Reviewer decides." in body
    assert 'data-testid="recommendation-outcome">deny<' in front_body
    assert "DF-1" in front_body and "ACME Code §14-305" in front_body
    assert 'data-testid="recommendation-outcome">approve<' in rear_body

    # 4. Steward: navigation is scoped; approve the applicant identity link.
    choose(client, "persona_data_steward")
    assert 'data-screen-key="governance"' not in client.get("/queue").text
    assert client.get("/governance").status_code == 403
    approve_applicant_link(environment, rear_id)
    approve_applicant_link(environment, front_id)

    # 5. Reviewer: deny the front fence (DF-1), approve the rear fence.
    choose(client, "persona_permit_reviewer")

    def decide(application_id: str, outcome: str, reason: str) -> None:
        version = application_row(environment, application_id)["version"]
        act(
            client,
            "permit.decide",
            {
                "application_id": application_id,
                "expected_application_version": str(version),
                "outcome": outcome,
                "reason": reason,
            },
            f"/permits/{application_id}",
        )

    decide(front_id, "denied", "Front fence fails DF-1; agrees with the agent recommendation.")
    decide(rear_id, "approved", "Rear fence complies with DF-2; agrees with the recommendation.")
    assert application_row(environment, front_id)["status"] == "denied"
    assert application_row(environment, rear_id)["status"] == "approved"

    # 6a. Administrator assesses the approved case; amounts come from responses.
    choose(client, "persona_city_administrator")
    rear_state = application_row(environment, rear_id)
    assessed = client.post(
        "/api/finance/assessments",
        json={
            "application_id": rear_id,
            "valuation": rear_state["facts"].get("valuation"),
            "reason": "fence use case assessment",
            "expected_application_version": rear_state["version"],
        },
    )
    assert assessed.status_code == 200, assessed.text
    assessment = assessed.json()
    total = assessment["assessed_total"]

    imported = client.post(
        "/api/finance/payments",
        json={
            "source_transaction_id": "ERP-TXN-FENCE-001",
            "source_event_id": "ERP-EVT-FENCE-001-1",
            "event_type": "received",
            "amount": total,
            "currency": "USD",
            "party_id": "party_applicant_1",
            "reason": "fence use case payment",
        },
    )
    assert imported.status_code == 200, imported.text
    payment_id = imported.json()["payment_id"]
    settled = client.post(
        "/api/finance/payments",
        json={
            "source_transaction_id": "ERP-TXN-FENCE-001",
            "source_event_id": "ERP-EVT-FENCE-001-2",
            "event_type": "settled",
            "amount": total,
            "currency": "USD",
            "reason": "fence use case settlement",
        },
    )
    assert settled.status_code == 200, settled.text

    allocated = client.post(
        "/api/finance/allocations",
        json={
            "payment_id": payment_id,
            "assessment_id": assessment["assessment_id"],
            "amount": total,
            "currency": "USD",
            "idempotency_key": "alloc:fence-use-case",
            "reason": "fence use case allocation",
        },
    )
    assert allocated.status_code == 200, allocated.text
    reconciled = client.post(
        "/api/finance/reconciliations",
        json={"assessment_id": assessment["assessment_id"], "payment_ids": [payment_id]},
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["balance"] == "0.00"
    assert reconciled.json()["status"] == "exact"

    # 6b. Reviewer issues the approved rear permit; the denied case stays denied.
    choose(client, "persona_permit_reviewer")
    rear_state = application_row(environment, rear_id)
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            decision = session.execute(
                select(permit.Decision).where(
                    permit.Decision.application_id == rear_id,
                    permit.Decision.status == "current",
                )
            ).scalar_one()
            decision_id, decision_version = decision.id, decision.version
    finally:
        factory.dispose()
    issued = client.post(
        f"/api/permits/applications/{rear_id}/issue",
        json={
            "decision_id": decision_id,
            "expected_application_version": rear_state["version"],
            "expected_decision_version": decision_version,
            "command_key": f"issue-fence-{rear_id}",
            "reason": "fence use case issuance",
        },
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["value"]["permit_number"].startswith("ACME-")
    assert application_row(environment, rear_id)["status"] == "issued"
    assert application_row(environment, front_id)["status"] == "denied"
