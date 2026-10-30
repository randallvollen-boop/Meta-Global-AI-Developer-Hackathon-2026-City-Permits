"""The Agent Operator home and its four navigation destinations.

The Agent processing tab of the administration screen belongs to the same
lane: the administrator saves the processing policy there, and the operator
reads the saved state on the agent screens.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.agents.policy import current_policy
from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import agent_ops, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


def _seed(settings: Settings) -> None:
    """Create the database of the settings and reset the demonstration."""
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


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'operator-ui.db'}",
            "ACME_SECRET_KEY": "operator-ui-test-secret",
        },
        key_file=tmp_path / "missing.env",
    )
    _seed(settings)
    return settings


@pytest.fixture()
def client(environment: Settings):
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        assert test_client.post("/api/session/select", json={"actor_id": "persona_agent_operator"}).status_code == 200
        yield test_client


@pytest.fixture()
def admin_client(environment: Settings):
    """Return a client that acts as the City Administrator."""
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        assert test_client.post(
            "/api/session/select", json={"actor_id": "persona_city_administrator"}
        ).status_code == 200
        yield test_client


@pytest.fixture()
def hosted_admin_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Return an administrator's client of a hosted demonstration.

    The provider lock of a hosted deployment is on, so the daily allowance
    of provider calls is zero whatever a request asks for.  The credential
    is an inert test only value: it never leaves this process.
    """
    monkeypatch.setenv("ACME_PUBLIC_DEMO", "true")
    monkeypatch.setenv("ACME_KEY_FILE", str(tmp_path / "missing.env"))
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'hosted-processing.db'}",
            "ACME_SECRET_KEY": "hosted-processing-test-secret-value",
            "META_API_KEY": "hosted-test-only-not-a-real-credential",
            "ACME_PUBLIC_DEMO": "true",
        },
        key_file=tmp_path / "missing.env",
    )
    _seed(settings)
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        assert test_client.post(
            "/api/session/select", json={"actor_id": "persona_city_administrator"}
        ).status_code == 200
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


def test_the_administrator_opens_the_agent_processing_tab(
    admin_client: TestClient,
) -> None:
    """The tab shows the saved policy and the control that changes it."""
    page = admin_client.get("/admin?tab=agent_processing")
    assert page.status_code == 200, page.text
    assert 'data-testid="admin-agent-processing"' in page.text
    assert "Keep agents awake" in page.text
    assert 'data-testid="admin-processing-mode"' in page.text
    # The tab is a tab of the administration screen and carries the current one.
    assert 'data-tab="agent_processing"' in page.text
    assert 'aria-current="page"' in page.text


def test_the_operator_does_not_see_the_agent_processing_tab(
    client: TestClient,
) -> None:
    """The policy is the administrator's; the operator reads it elsewhere."""
    assert client.get("/admin?tab=agent_processing").status_code == 403


def test_the_administrator_saves_the_processing_settings(
    admin_client: TestClient, environment: Settings
) -> None:
    """The saved policy is the one the database holds, not the one of the form."""
    path = "/admin?tab=agent_processing"
    saved = act(
        admin_client,
        "admin.agent.processing",
        {
            "keep_awake": "true",
            "runs_per_hour": "42",
            "reason": "Evening coverage",
            "expected_version": "1",
        },
        path,
    )
    assert saved["status"] == "accepted", saved
    assert saved["message"] == "The processing settings were saved."
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            policy = current_policy(session)
            assert policy is not None
            assert policy.mode == "automatic"
            assert policy.runs_per_hour == 42
    finally:
        factory.dispose()
    # The screen shows the saved state and the name of the person who saved it.
    page = admin_client.get(path)
    assert "Automatic processing" in page.text
    assert "City Administrator" in page.text


def test_a_stale_save_of_the_processing_settings_is_refused(
    admin_client: TestClient,
) -> None:
    """Two administrators never overwrite each other in silence."""
    path = "/admin?tab=agent_processing"
    refused = admin_client.post(
        "/ui/actions/admin.agent.processing",
        data={
            "csrf_token": csrf(admin_client, path),
            "action_id": "admin.agent.processing",
            "next": path,
            "keep_awake": "true",
            "runs_per_hour": "30",
            "reason": "Stale save",
            "expected_version": "99",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert refused.status_code == 422, refused.text
    payload = refused.json()
    assert payload["status"] == "denied", payload
    assert "changed since they were read" in payload["message"], payload


def test_a_non_administrator_cannot_save_the_processing_settings(
    client: TestClient,
) -> None:
    """The saving action of the tab is the administrator's own."""
    path = "/admin?tab=agent_processing"
    refused = client.post(
        "/ui/actions/admin.agent.processing",
        data={
            "csrf_token": csrf(client, "/agent/intake"),
            "action_id": "admin.agent.processing",
            "next": path,
            "keep_awake": "true",
            "runs_per_hour": "30",
            "reason": "No authority",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert refused.status_code == 403, refused.text


def test_a_hosted_deployment_refuses_to_raise_the_live_call_allowance(
    hosted_admin_client: TestClient,
) -> None:
    """The provider lock of the deployment wins over any configuration.

    The tab shows the locked allowance of zero, and a request that asks for
    more is refused before anything is saved.
    """
    path = "/admin?tab=agent_processing"
    page = hosted_admin_client.get(path)
    assert page.status_code == 200, page.text
    assert "Locked for this hosted demo." in page.text
    refused = hosted_admin_client.post(
        "/ui/actions/admin.agent.processing",
        data={
            "csrf_token": csrf(hosted_admin_client, path),
            "action_id": "admin.agent.processing",
            "next": path,
            "keep_awake": "true",
            "runs_per_hour": "30",
            "muse_daily_call_cap": "5",
            "reason": "No authority",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert refused.status_code == 422, refused.text
    payload = refused.json()
    assert payload["status"] == "denied", payload
    assert "locked" in payload["message"], payload
