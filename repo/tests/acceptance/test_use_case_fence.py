"""USE_CASE_FENCE: the documented manual fence walkthrough, automated.

Follows docs/operations/USE_CASE_FENCE.md step by step through the real HTTP
surface (the same governed endpoints and UI actions the browser posts to):
the administrator simulates the two fence scenarios, wakes the intake agent,
the data steward runs the intake agent and approves the links and the
extracted values, the administrator wakes the adjudication agent, the permit
reviewer runs it and confirms the denial and reverts the approval, then fee
assessment, payment, allocation, reconciliation and issuance for the approved
case.  Amounts are always read from API responses, never assumed.
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
from acme_city.persistence.models import gis, permit, registry
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
                "review_area": row.review_area,
            }
    finally:
        factory.dispose()


def evaluation_version(settings, application_id: str) -> int:
    """Return the version of the current evaluation, which a decision is made against."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return session.execute(
                select(permit.Evaluation.version)
                .where(permit.Evaluation.application_id == application_id)
                .order_by(permit.Evaluation.version.desc())
            ).scalars().first()
    finally:
        factory.dispose()


def proposed_links(settings) -> list[dict]:
    """Return the proposed identity links of the demonstration."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.link_status == "proposed"
                )
            ).scalars().all()
            return [
                {
                    "crosswalk_id": row.id,
                    "entity_id": row.entity_id,
                    "source_system_id": row.source_system_id,
                    "source_dataset_key": row.source_dataset_key,
                    "source_record_id": row.source_record_id,
                    "version": row.version,
                }
                for row in rows
            ]
    finally:
        factory.dispose()


def proposed_observations(settings) -> list[dict]:
    """Return the proposed extracted values of the demonstration."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(permit.ExtractionObservation).where(
                    permit.ExtractionObservation.validation_state == "proposed"
                )
            ).scalars().all()
            entries: list[dict] = []
            for row in rows:
                document = session.get(permit.Document, row.document_id)
                entries.append(
                    {
                        "observation_id": row.id,
                        "field_path": row.field_path,
                        "document_id": row.document_id,
                        "application_id": (
                            document.application_id if document is not None else ""
                        ),
                    }
                )
            return entries
    finally:
        factory.dispose()


def approve_links_and_values(client: TestClient, settings) -> None:
    """Approve every proposed link and every proposed extracted value."""
    for link in proposed_links(settings):
        act(
            client,
            "registry.decide",
            {
                "decision": "approve",
                "reason": "the applicant named the party on the application",
                "source_system_id": link["source_system_id"],
                "dataset_key": link["source_dataset_key"],
                "source_record_id": link["source_record_id"],
                "entity_id": link["entity_id"],
                "expected_version": str(link["version"]),
            },
            "/steward",
        )
    for observation in proposed_observations(settings):
        act(
            client,
            "extraction.decide",
            {
                "observation_id": observation["observation_id"],
                "decision": "accept",
                "reason": "the value is quoted from the received document",
                "application_id": observation["application_id"],
            },
            "/steward",
        )


def parcel_match_version(settings, application_id: str) -> int:
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return session.execute(
                select(gis.ApplicationParcelMatch).where(
                    gis.ApplicationParcelMatch.application_id == application_id
                )
            ).scalar_one().version
    finally:
        factory.dispose()


def approve_parcel_link(client: TestClient, settings, application_id: str) -> None:
    result = act(
        client,
        "parcel.link.decide",
        {
            "application_id": application_id,
            "decision": "approve",
            "expected_version": str(parcel_match_version(settings, application_id)),
            "reason": "the corrected address falls inside this parcel",
        },
        "/steward",
    )
    assert result["status"] == "accepted", result


def test_use_case_fence(client: TestClient, environment) -> None:
    # 1-2. Administrator simulates both fence scenarios; they wait.
    choose(client, "persona_city_administrator")
    assert 'data-action-id="intake.simulate"' in client.get("/governance").text
    front = simulate(client, "fence-front-too-tall")
    rear = simulate(client, "fence-conforming-rear")
    front_id, rear_id = front["application_id"], rear["application_id"]
    for application_id in (front_id, rear_id):
        state = application_row(environment, application_id)
        assert state["status"] == "submitted"

    # 3. The agent operator wakes the intake agent.
    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.toggle",
        {"agent_key": "intake", "mode": "awake"},
        "/agent/intake",
    )
    intake_screen = client.get("/agent/intake").text
    assert 'data-testid="agent-mode">awake<' in intake_screen

    # 4. The agent operator runs the intake agent on all waiting cases.
    choose(client, "persona_data_steward")
    assert 'data-screen-key="governance"' not in client.get("/queue").text
    assert client.get("/governance").status_code == 403
    choose(client, "persona_agent_operator")
    run_all = act(client, "agent.run.intake", {}, "/agent/intake")
    assert run_all["status"] == "accepted", run_all
    for application_id in (front_id, rear_id):
        state = application_row(environment, application_id)
        assert state["status"] == "ready_for_review"
        assert state["review_area"] == "Building"
    trace = client.get("/agent/intake").text
    for node in (
        "classifier",
        "field_extractor",
        "document_qc",
        "duplicate_finder",
        "completeness",
        "router",
    ):
        assert f'data-node-id="{node}"' in trace

    # 5. The steward approves the proposed links and the extracted values.
    # The applicant typed "400 Lantren Row": the locator corrected it to the
    # official address and proposed the parcel; the steward approves that link.
    choose(client, "persona_data_steward")
    for application_id in (front_id, rear_id):
        body = client.get(f"/permits/{application_id}").text
        assert "400 Lantren Row" in body and "ACME-P-1001" in body
    approve_links_and_values(client, environment)
    for application_id in (front_id, rear_id):
        approve_parcel_link(client, environment, application_id)

    # 6. The agent operator wakes the adjudication agent.
    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.toggle",
        {"agent_key": "adjudication", "mode": "awake"},
        "/agent/adjudication",
    )

    # 7. The agent operator runs the adjudication agent on all cases in review.
    choose(client, "persona_permit_reviewer")
    assert client.get("/agent/intake").status_code == 403
    choose(client, "persona_agent_operator")
    run_all = act(client, "agent.run.adjudication", {}, "/agent/adjudication")
    assert run_all["status"] == "accepted", run_all

    # The case pages belong to the reviewer, who reads the recommendation.
    choose(client, "persona_permit_reviewer")
    front_body = client.get(f"/permits/{front_id}").text
    rear_body = client.get(f"/permits/{rear_id}").text
    assert 'data-testid="recommendation-outcome">deny<' in front_body
    assert "DF-1" in front_body and "ACME Code §14-305" in front_body
    assert 'data-testid="recommendation-outcome">approve<' in rear_body
    assert "DF-2" in rear_body and "ACME Code §14-306" in rear_body

    # 8. The reviewer confirms the denial; the decision of record is theirs.
    front_version = application_row(environment, front_id)["version"]
    confirmed = act(
        client,
        "recommendation.confirm",
        {
            "recommendation_id": _pending_recommendation_id(environment, front_id),
            "application_id": front_id,
            "expected_application_version": str(front_version),
            "reason": "the front fence fails DF-1",
            # A denial names an active denial reason code.
            "reason_code": "DOES_NOT_MEET_CODE",
        },
        f"/permits/{front_id}",
    )
    assert confirmed["status"] == "accepted", confirmed
    front_state = application_row(environment, front_id)
    assert front_state["status"] == "denied"

    # 9. The reviewer reverts the approval with a reason and decides it.
    rear_version = application_row(environment, rear_id)["version"]
    reverted = act(
        client,
        "recommendation.revert",
        {
            "recommendation_id": _pending_recommendation_id(environment, rear_id),
            "application_id": rear_id,
            "reason": "I want to check the setback myself before approving",
        },
        f"/permits/{rear_id}",
    )
    assert reverted["status"] == "accepted", reverted
    assert application_row(environment, rear_id)["status"] == "under_review"

    # The approval is blocked until the reviewer confirms the parcel.
    rear_version = application_row(environment, rear_id)["version"]
    blocked = client.post(
        "/ui/actions/permit.decide",
        data={
            "csrf_token": csrf(client, f"/permits/{rear_id}"),
            "application_id": rear_id,
            "expected_application_version": str(rear_version),
            "expected_evaluation_version": str(evaluation_version(environment, rear_id)),
            "outcome": "approved",
            "reason": "premature",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert blocked.status_code == 422 or blocked.json()["status"] == "denied"
    confirmed_parcel = act(
        client,
        "parcel.confirm",
        {
            "application_id": rear_id,
            "expected_version": str(parcel_match_version(environment, rear_id)),
            "reason": "this is the right property",
        },
        f"/permits/{rear_id}",
    )
    assert confirmed_parcel["status"] == "accepted", confirmed_parcel

    rear_version = application_row(environment, rear_id)["version"]
    # The reviewer leaves the applicant a comment before deciding.
    commented = act(
        client,
        "permit.case.comment",
        {
            "application_id": rear_id,
            "expected_version": str(rear_version),
            "body": "The rear fence complies with DF-2. The gate must open inward.",
            "visibility": "applicant",
        },
        f"/permits/{rear_id}",
    )
    assert commented["status"] == "accepted", commented

    rear_version = application_row(environment, rear_id)["version"]
    decided = act(
        client,
        "permit.decide",
        {
            "application_id": rear_id,
            "expected_application_version": str(rear_version),
            "expected_evaluation_version": str(evaluation_version(environment, rear_id)),
            "outcome": "approved_with_conditions",
            "conditions": "The gate must open inward.",
            "reason": "the rear fence complies with DF-2",
        },
        f"/permits/{rear_id}",
    )
    assert decided["status"] == "accepted", decided
    assert application_row(environment, rear_id)["status"] == "approved"

    # 10. The administrator assesses the approved case; amounts come from
    # responses.
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

    # 11. The reviewer issues the approved rear permit; the denied case stays
    # denied.
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
            decided_by = decision.decided_by_actor_id
    finally:
        factory.dispose()
    assert decided_by == "persona_permit_reviewer"
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
    # The conditions of the approval are part of the immutable record.
    snapshot = issued.json()["value"]["snapshot"]
    assert snapshot["decision"]["conditions"] == ["The gate must open inward."]


def _pending_recommendation_id(settings, application_id: str) -> str:
    """Return the identifier of the pending recommendation of a case."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            row = session.execute(
                select(permit.Recommendation).where(
                    permit.Recommendation.application_id == application_id,
                    permit.Recommendation.status == "pending",
                )
            ).scalar_one()
            return row.id
    finally:
        factory.dispose()
