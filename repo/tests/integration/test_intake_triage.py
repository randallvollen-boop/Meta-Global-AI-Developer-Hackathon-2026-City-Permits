"""Simulated outside intake and the two people-driven agents.

An intake record is staged through its registered contract and becomes a
Permitting application plus revision plus document version.  Nothing else
happens on arrival: the case waits as "Awaiting intake agent" until a City
Administrator wakes the intake agent and a person runs it.  The adjudication
agent recommends; a person confirms or reverts.
"""

from __future__ import annotations

import re
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
from acme_city.persistence.models import gis, permit
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


def wake(client: TestClient, agent_key: str) -> None:
    """Wake one agent as the Agent Operator, the persona that may run it."""
    choose(client, "persona_agent_operator")
    result = act(
        client,
        "agent.toggle",
        {"agent_key": agent_key, "mode": "awake"},
        f"/agent/{agent_key}",
    )
    assert result["status"] == "accepted", result


def application_row(settings, application_id: str) -> dict:
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


def parcel_match_row(settings, application_id: str) -> gis.ApplicationParcelMatch:
    """Return the parcel match of one case."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return session.execute(
                select(gis.ApplicationParcelMatch).where(
                    gis.ApplicationParcelMatch.application_id == application_id
                )
            ).scalar_one()
    finally:
        factory.dispose()


def approve_parcel_link(client: TestClient, settings, application_id: str) -> None:
    """The Data Steward confirms the parcel the address locator proposed."""
    choose(client, "persona_data_steward")
    result = act(
        client,
        "parcel.link.decide",
        {
            "application_id": application_id,
            "decision": "approve",
            "expected_version": str(parcel_match_row(settings, application_id).version),
            "reason": "the corrected address falls inside this parcel",
        },
        "/steward",
    )
    assert result["status"] == "accepted", result


def test_intake_portal_is_registered_and_shows_in_governance(client: TestClient) -> None:
    choose(client, "persona_city_administrator")
    body = client.get("/governance").text
    assert "intake_portal" in body
    assert "submitted_applications" in body
    systems = client.get("/api/sources/systems").json()
    ids = {row["source_system_id"] for row in systems["source_systems"]}
    assert "intake_portal" in ids


def test_a_new_record_waits_for_the_intake_agent(client: TestClient, environment) -> None:
    choose(client, "persona_data_steward")
    (result,) = simulate(client, "fence-conforming-rear")
    assert result["status"] == "created"
    assert result["triage_outcome"] == "awaiting_intake_agent"
    state = application_row(environment, result["application_id"])
    assert state["status"] == "submitted"
    queue = client.get("/queue?view=all").text
    assert "Awaiting intake agent" in queue


def test_the_intake_agent_sleeps_until_the_operator_wakes_it(
    client: TestClient, environment
) -> None:
    choose(client, "persona_agent_operator")
    (result,) = simulate(client, "fence-conforming-rear")
    application_id = result["application_id"]
    # The agent sleeps, so a run is refused.
    refused = client.post(
        "/ui/actions/agent.run.intake",
        data={
            "csrf_token": csrf(client, "/agent/intake"),
            "action_id": "agent.run.intake",
            "next": "/agent/intake",
            "application_id": application_id,
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert refused.status_code == 422, refused.text
    assert application_row(environment, application_id)["status"] == "submitted"

    wake(client, "intake")
    choose(client, "persona_agent_operator")
    accepted = act(
        client,
        "agent.run.intake",
        {"application_id": application_id},
        "/agent/intake",
    )
    assert accepted["status"] == "accepted", accepted
    state = application_row(environment, application_id)
    assert state["status"] == "ready_for_review"
    assert state["review_area"] == "Building"


def test_the_operator_may_run_the_agents_but_may_not_decide(
    client: TestClient, environment
) -> None:
    choose(client, "persona_agent_operator")
    wake(client, "intake")
    (result,) = simulate(client, "fence-conforming-rear")
    application_id = result["application_id"]
    accepted = act(
        client,
        "agent.run.intake",
        {"application_id": application_id},
        "/agent/intake",
    )
    assert accepted["status"] == "accepted", accepted
    # Neither the Agent Operator nor the City Administrator holds business
    # approval authority.
    choose(client, "persona_city_administrator")
    refused = client.post(
        "/ui/actions/recommendation.confirm",
        data={
            "csrf_token": csrf(client, f"/permits/{application_id}"),
            "action_id": "recommendation.confirm",
            "next": f"/permits/{application_id}",
            "application_id": application_id,
            "recommendation_id": "rec_does_not_exist",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert refused.status_code in (403, 404), refused.text


def test_the_rear_fence_is_routed_to_the_building_review_area(
    client: TestClient, environment
) -> None:
    choose(client, "persona_data_steward")
    (result,) = simulate(client, "fence-conforming-rear")
    application_id = result["application_id"]
    wake(client, "intake")
    choose(client, "persona_agent_operator")
    act(client, "agent.run.intake", {"application_id": application_id}, "/agent/intake")
    state = application_row(environment, application_id)
    assert state["status"] == "ready_for_review"
    assert state["review_area"] == "Building"
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            findings = session.execute(
                select(permit.ApplicationFinding).where(
                    permit.ApplicationFinding.application_id == application_id
                )
            ).scalars().all()
            assert findings == []
            runs = session.execute(
                select(agent_models.AgentRun).where(
                    agent_models.AgentRun.application_id == application_id
                )
            ).scalars().all()
            assert len(runs) == 1
            nodes = session.execute(
                select(agent_models.AgentRunNode).where(
                    agent_models.AgentRunNode.agent_run_id == runs[0].id
                ).order_by(agent_models.AgentRunNode.position)
            ).scalars().all()
            assert [node.node_id for node in nodes] == [
                "classifier",
                "field_extractor",
                "document_qc",
                "address_locator",
                "completeness",
                "duplicate_finder",
                "router",
            ]
            assert {node.status for node in nodes} <= {"ok", "warn", "block"}
    finally:
        factory.dispose()


def test_a_missing_site_plan_is_routed_to_early_resolution(
    client: TestClient, environment
) -> None:
    choose(client, "persona_data_steward")
    (result,) = simulate(client, "fence-missing-site-plan")
    application_id = result["application_id"]
    wake(client, "intake")
    choose(client, "persona_agent_operator")
    act(client, "agent.run.intake", {"application_id": application_id}, "/agent/intake")
    assert application_row(environment, application_id)["status"] == "needs_information"
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            findings = session.execute(
                select(permit.ApplicationFinding).where(
                    permit.ApplicationFinding.application_id == application_id
                )
            ).scalars().all()
            kinds = {row.finding_type for row in findings}
            assert "missing_document" in kinds
            assert all(row.severity == "block" for row in findings)
            assert all(row.applicant_must for row in findings)
    finally:
        factory.dispose()


def test_the_duplicate_finder_links_the_resubmission_to_the_original(
    client: TestClient, environment
) -> None:
    choose(client, "persona_data_steward")
    results = simulate(client, "duplicate-fence")
    assert len(results) == 2
    original_id, repeat_id = results[0]["application_id"], results[1]["application_id"]
    wake(client, "intake")
    choose(client, "persona_agent_operator")
    act(client, "agent.run.intake", {"application_id": original_id}, "/agent/intake")
    act(client, "agent.run.intake", {"application_id": repeat_id}, "/agent/intake")
    assert application_row(environment, repeat_id)["status"] == "needs_information"
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            findings = session.execute(
                select(permit.ApplicationFinding).where(
                    permit.ApplicationFinding.application_id == repeat_id,
                    permit.ApplicationFinding.finding_type == "duplicate",
                )
            ).scalars().all()
            assert len(findings) == 1
            assert findings[0].related_application_id == original_id
    finally:
        factory.dispose()


def test_an_unreadable_fax_page_blocks_the_case(client: TestClient, environment) -> None:
    choose(client, "persona_data_steward")
    (result,) = simulate(client, "fax-unreadable")
    application_id = result["application_id"]
    wake(client, "intake")
    choose(client, "persona_agent_operator")
    act(client, "agent.run.intake", {"application_id": application_id}, "/agent/intake")
    assert application_row(environment, application_id)["status"] == "needs_information"
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            findings = session.execute(
                select(permit.ApplicationFinding).where(
                    permit.ApplicationFinding.application_id == application_id,
                    permit.ApplicationFinding.finding_type == "unreadable",
                )
            ).scalars().all()
            assert len(findings) == 1
            assert findings[0].severity == "block"
    finally:
        factory.dispose()


def test_the_adjudication_agent_recommends_deny_and_approve(
    client: TestClient, environment
) -> None:
    choose(client, "persona_data_steward")
    (front,) = simulate(client, "fence-front-too-tall")
    (rear,) = simulate(client, "fence-conforming-rear")
    wake(client, "intake")
    choose(client, "persona_agent_operator")
    act(client, "agent.run.intake", {"application_id": front["application_id"]}, "/agent/intake")
    act(client, "agent.run.intake", {"application_id": rear["application_id"]}, "/agent/intake")
    # The Data Steward confirms the parcel of both cases: the parcel inputs
    # come from the parcel the steward confirms.
    approve_parcel_link(client, environment, front["application_id"])
    approve_parcel_link(client, environment, rear["application_id"])

    wake(client, "adjudication")
    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.run.adjudication",
        {"application_id": front["application_id"]},
        "/agent/adjudication",
    )
    act(
        client,
        "agent.run.adjudication",
        {"application_id": rear["application_id"]},
        "/agent/adjudication",
    )

    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            front_rec = session.execute(
                select(permit.Recommendation).where(
                    permit.Recommendation.application_id == front["application_id"],
                    permit.Recommendation.status == "pending",
                )
            ).scalar_one()
            rear_rec = session.execute(
                select(permit.Recommendation).where(
                    permit.Recommendation.application_id == rear["application_id"],
                    permit.Recommendation.status == "pending",
                )
            ).scalar_one()
            assert front_rec.proposed_outcome == "deny"
            assert "DF-1" in (front_rec.rationale or "")
            assert "ACME Code §14-305" in (front_rec.rationale or "")
            assert "6 ft" in (front_rec.rationale or "")
            assert rear_rec.proposed_outcome == "approve"
            assert "DF-2" in (rear_rec.rationale or "")
            # The rationale cites each rule once.
            assert (rear_rec.rationale or "").count("DF-2") == 1
    finally:
        factory.dispose()


def test_the_adjudication_agent_waits_for_the_steward_while_the_parcel_is_unconfirmed(
    client: TestClient, environment
) -> None:
    """An unresolved property is not a case the agent may recommend on.

    The parcel inputs (zoning, flood zone) come from the parcel the Data
    Steward confirms.  While the link the address locator proposed is not
    confirmed, the agent does not recommend approval: it holds the case and
    the case waits for the Data Steward.
    """
    choose(client, "persona_data_steward")
    (rear,) = simulate(client, "fence-conforming-rear")
    application_id = rear["application_id"]
    wake(client, "intake")
    choose(client, "persona_agent_operator")
    act(client, "agent.run.intake", {"application_id": application_id}, "/agent/intake")
    wake(client, "adjudication")
    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.run.adjudication",
        {"application_id": application_id},
        "/agent/adjudication",
    )

    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            recommendation = session.execute(
                select(permit.Recommendation).where(
                    permit.Recommendation.application_id == application_id,
                    permit.Recommendation.status == "pending",
                )
            ).scalar_one()
            assert recommendation.proposed_outcome == "hold"
            assert (
                "Cannot recommend yet: the parcel is not confirmed. "
                "Waiting on Data Steward." in (recommendation.rationale or "")
            )
    finally:
        factory.dispose()

    # The case waits for the Data Steward, and the page says so.
    choose(client, "persona_permit_reviewer")
    page = client.get(f"/permits/{application_id}").text
    assert 'data-testid="recommendation-outcome">Hold<' in page
    assert "Waiting on Data Steward" in page

    # Once the steward confirms the parcel, a re-run evaluates all the rules.
    approve_parcel_link(client, environment, application_id)
    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.run.adjudication",
        {"application_id": application_id},
        "/agent/adjudication",
    )
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            recommendation = session.execute(
                select(permit.Recommendation).where(
                    permit.Recommendation.application_id == application_id,
                    permit.Recommendation.status == "pending",
                )
            ).scalar_one()
            assert recommendation.proposed_outcome == "approve"
            assert "DF-2" in (recommendation.rationale or "")
            evaluation = session.execute(
                select(permit.Evaluation).where(
                    permit.Evaluation.application_id == application_id,
                    permit.Evaluation.status == "current",
                )
            ).scalar_one()
            assert [row["rule_id"] for row in evaluation.results or []] == ["DF-2"]
    finally:
        factory.dispose()


def test_a_discretionary_type_is_held_for_a_person(
    client: TestClient, environment
) -> None:
    choose(client, "persona_data_steward")
    (result,) = simulate(client, "variance-request")
    application_id = result["application_id"]
    wake(client, "intake")
    choose(client, "persona_agent_operator")
    act(client, "agent.run.intake", {"application_id": application_id}, "/agent/intake")
    wake(client, "adjudication")
    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.run.adjudication",
        {"application_id": application_id},
        "/agent/adjudication",
    )
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            recommendation = session.execute(
                select(permit.Recommendation).where(
                    permit.Recommendation.application_id == application_id,
                    permit.Recommendation.status == "pending",
                )
            ).scalar_one()
            assert recommendation.proposed_outcome == "hold"
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


def test_the_random_scenario_is_deterministic_across_every_type(
    client: TestClient
) -> None:
    choose(client, "persona_data_steward")
    first = simulate(client, "random")
    assert len(first) == 5
    references = [row["portal_reference"] for row in first]
    choose(client, "persona_data_steward")
    second = simulate(client, "random")
    assert [row["portal_reference"] for row in second] == references
