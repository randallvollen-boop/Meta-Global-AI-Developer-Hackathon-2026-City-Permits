"""The Agent Operator home and its four navigation destinations."""

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
from acme_city.persistence.models import agent_ops, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'operator-ui.db'}",
            "ACME_SECRET_KEY": "operator-ui-test-secret",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(DemoEnvironment(
                id="demo_environment_local", environment_id=ENVIRONMENT_ID,
                fictional_demo=True, fixture_version=bundle.fixture_version,
                label="local fictional demonstration",
            ))
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    finally:
        factory.dispose()
    return settings


@pytest.fixture()
def client(environment: Settings):
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        assert test_client.post("/api/session/select", json={"actor_id": "persona_agent_operator"}).status_code == 200
        yield test_client


def csrf(client: TestClient, path: str) -> str:
    """Return the CSRF token of one screen of the current session."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def act(client: TestClient, action_id: str, fields: dict, next_path: str) -> dict:
    """Run one action of the interface and return its typed outcome."""
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


def test_operator_lands_on_agents_and_all_four_navigation_links_work(client: TestClient) -> None:
    response = client.post("/ui/actor", data={"actor_id": "persona_agent_operator", "next": "/agents"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/agents"
    page = client.get("/agents")
    assert page.status_code == 200
    assert "<h1>Agents</h1>" in page.text
    for href in ("/agents", "/agent/intake", "/agent/adjudication", "/agents/runs"):
        assert f'href="{href}"' in page.text
        assert client.get(href).status_code == 200


def test_a_controlled_case_is_refused_by_a_direct_run(
    client: TestClient, environment: Settings
) -> None:
    """A case of the fixed demonstration is never worked, not by a direct post.

    The screen does not list these cases, so only a direct post names one.
    The refusal leaves the case exactly as it was.
    """
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.execute(
                select(permit.Application).where(
                    permit.Application.scenario_id == "D01"
                )
            ).scalars().first()
            assert row is not None
            application_id = row.id
            status = row.status
            version = row.version
    finally:
        factory.dispose()
    # The agent is awake, so the refusal is about the case and not the sleep.
    wake = act(
        client,
        "agent.toggle",
        {"agent_key": "intake", "mode": "awake"},
        "/agent/intake",
    )
    assert wake["status"] == "accepted", wake
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
    payload = refused.json()
    assert payload["status"] == "denied", payload
    assert "controlled demonstration case" in payload["message"], payload
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.get(permit.Application, application_id)
            assert row is not None
            assert row.status == status
            assert row.version == version
            queued = session.execute(select(agent_ops.AgentWorkQueue)).scalars().all()
            assert queued == []
    finally:
        factory.dispose()
