"""The demonstration data of the steward assistant.

The demonstration database holds three tasks in the queue of the Data
Steward, one for each certainty the assistant can reach: a link it is sure
of, a link it is not sure of and an issue whose two versions disagree.

Fictional ACME City data only.
"""
# REQUIRES: MDM-02, UX-01

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.agents.control import AgentControlService
from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_assist_demo import seed_steward_assistant_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

STEWARD = ActorContext(
    actor_id="persona_data_steward", role_ids=frozenset({"domain_steward"})
)
OPERATOR = ActorContext(
    actor_id="persona_agent_operator", role_ids=frozenset({"agent_operator"})
)


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'steward-demo-data.db'}",
            "ACME_SECRET_KEY": "steward-demo-data-secret-value",
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
        with transaction(factory) as session:
            seed_steward_assistant_demo(session, bundle)
    finally:
        factory.dispose()
    return settings


@pytest.fixture()
def client(environment: Settings) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def csrf(client: TestClient, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def post(client: TestClient, action: str, fields: dict[str, str], next_path: str):
    return client.post(
        f"/ui/actions/{action}",
        data={"csrf_token": csrf(client, next_path), "next": next_path, **fields},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


def wake_the_assistant(client: TestClient) -> None:
    """Wake the steward assistant, the way the Agent Operator does."""
    choose(client, "persona_agent_operator")
    response = client.post(
        "/ui/actions/agent.toggle",
        data={
            "csrf_token": csrf(client, "/agent/steward_assist"),
            "next": "/agent/steward_assist",
            "agent_key": "steward_assist",
            "mode": "awake",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text
    choose(client, "persona_data_steward")


def test_the_demo_data_holds_the_tasks_of_the_queue(
    client: TestClient, environment: Settings
) -> None:
    """The queue holds the tasks of the demonstration."""
    choose(client, "persona_data_steward")
    body = client.get("/steward?filter=needs_review").text
    rows = re.findall(r'data-issue-row[^>]*data-kind="([^"]+)"', body)
    assert sorted(rows) == ["issue", "link", "link", "link", "link"]


def test_the_assistant_reaches_every_level_on_the_demo_data(
    client: TestClient, environment: Settings
) -> None:
    """One press shows a High, a Review and a Held recommendation."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    response = post(client, "steward.assist.prepare", {"next": "/steward"}, "/steward")
    assert response.status_code == 200, response.text
    body = client.get("/steward?filter=needs_review").text
    pills = set(re.findall(r'data-testid="recommendation-pill">([^<]+)<', body))
    assert pills == {"High", "Review", "Held"}


def test_the_demo_data_decides_nothing(
    client: TestClient, environment: Settings
) -> None:
    """The links are proposed and the issue is open: the steward decides."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            from sqlalchemy import select

            from acme_city.persistence.models import change, registry

            links = session.execute(select(registry.Crosswalk)).scalars().all()
            assert links
            assert all(link.link_status == "proposed" for link in links)
            issues = session.execute(select(change.GovernanceIssue)).scalars().all()
            assert len(issues) == 1
            assert issues[0].status == "open"
    finally:
        factory.dispose()
