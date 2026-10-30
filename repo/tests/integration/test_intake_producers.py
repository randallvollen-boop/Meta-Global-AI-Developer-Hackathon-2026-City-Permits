"""The two new finding types and their producers in the intake graph.

The classifier confirms the permit type of a case.  It records a
``wrong_type`` finding when the record asked for another type, and a ``fee``
finding when the City cannot price the case.  A rerun settles the findings
of the earlier run.
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
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def environment(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'producers.db'}",
            "ACME_SECRET_KEY": "producer-test-secret-value",
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
    choose(client, "persona_agent_operator")
    result = act(
        client,
        "agent.toggle",
        {"agent_key": agent_key, "mode": "awake"},
        f"/agent/{agent_key}",
    )
    assert result["status"] == "accepted", result


def findings_of(environment, application_id: str) -> list[permit.ApplicationFinding]:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            return list(
                session.execute(
                    select(permit.ApplicationFinding)
                    .where(permit.ApplicationFinding.application_id == application_id)
                    .order_by(permit.ApplicationFinding.id)
                )
                .scalars()
                .all()
            )
    finally:
        factory.dispose()


def test_the_classifier_records_a_wrong_type_finding(
    client: TestClient, environment
) -> None:
    """A record that asked for another permit type is recorded as a wrong type."""
    choose(client, "persona_data_steward")
    (result,) = simulate(client, "fence-conforming-rear")
    application_id = result["application_id"]
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(permit.Application, application_id)
            facts = dict(application.submitted_facts or {})
            facts["permit_type_key"] = "shed"
            application.submitted_facts = facts
    finally:
        factory.dispose()
    wake(client, "intake")
    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.run.intake",
        {"application_id": application_id},
        "/agent/intake",
    )
    rows = findings_of(environment, application_id)
    wrong = [row for row in rows if row.finding_type == "wrong_type"]
    assert len(wrong) == 1
    assert wrong[0].severity == "review"
    assert wrong[0].state == "current"
    assert wrong[0].revision_number == 1
    assert "shed" in wrong[0].message


def test_the_classifier_records_a_fee_finding_when_the_case_cannot_be_priced(
    client: TestClient, environment
) -> None:
    """A permit type that names no fee schedule cannot be priced."""
    choose(client, "persona_data_steward")
    (result,) = simulate(client, "fence-conforming-rear")
    application_id = result["application_id"]
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(permit.Application, application_id)
            permit_type = session.get(permit.PermitType, application.permit_type_id)
            permit_type.fee_schedule_key = None
    finally:
        factory.dispose()
    wake(client, "intake")
    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.run.intake",
        {"application_id": application_id},
        "/agent/intake",
    )
    rows = findings_of(environment, application_id)
    fees = [row for row in rows if row.finding_type == "fee"]
    assert len(fees) == 1
    assert fees[0].severity == "block"
    assert "fee schedule" in fees[0].message


def test_a_rerun_supersedes_the_findings_of_the_first_run(
    client: TestClient, environment
) -> None:
    choose(client, "persona_data_steward")
    (result,) = simulate(client, "fence-missing-site-plan")
    application_id = result["application_id"]
    wake(client, "intake")
    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.run.intake",
        {"application_id": application_id},
        "/agent/intake",
    )
    first = findings_of(environment, application_id)
    assert first
    assert all(row.state == "current" for row in first)
    act(
        client,
        "agent.run.intake",
        {"application_id": application_id},
        "/agent/intake",
    )
    second = findings_of(environment, application_id)
    # The findings of the first run are kept, and they are superseded; the
    # rerun recorded the finding again.
    assert len(second) == len(first) + 1
    assert [row.state for row in second].count("superseded") == len(first)
    assert [row.state for row in second].count("current") == 1
    superseded = [row for row in second if row.state == "superseded"]
    assert all(row.superseded_at is not None for row in superseded)


def test_the_intake_agent_records_the_priority_of_the_record(
    client: TestClient, environment
) -> None:
    choose(client, "persona_data_steward")
    (result,) = simulate(client, "fence-conforming-rear")
    application_id = result["application_id"]
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(permit.Application, application_id)
            facts = dict(application.submitted_facts or {})
            facts["priority"] = "high"
            application.submitted_facts = facts
    finally:
        factory.dispose()
    wake(client, "intake")
    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.run.intake",
        {"application_id": application_id},
        "/agent/intake",
    )
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = session.get(permit.Application, application_id)
            assert application.priority == "high"
    finally:
        factory.dispose()
