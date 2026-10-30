"""The agreement figure on the queue of the Data Steward.

The figure shows the share of the recommendations the steward accepted
unchanged in the last seven days, with the counts it is made of.  When the
assistant prepared nothing lately, the figure says so plainly.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, PER-04

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
from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.models import audit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'steward-agreement.db'}",
            "ACME_SECRET_KEY": "steward-agreement-secret-value",
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
            seed_cedarline(session)
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


def test_the_figure_says_plainly_when_there_is_nothing_to_report(
    client: TestClient, environment: Settings
) -> None:
    """No recommendation in the last seven days is said plainly."""
    choose(client, "persona_data_steward")
    body = client.get("/steward").text
    assert 'data-testid="agreement-panel"' in body
    assert 'data-testid="agreement-empty"' in body
    assert "no recommendation" in body
    assert "7 days" in body


def test_the_figure_counts_the_recommendations_the_steward_accepted(
    client: TestClient, environment: Settings
) -> None:
    """The figure shows the counts it is made of."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    post(client, "steward.assist.prepare", {"next": "/steward"}, "/steward")
    body = client.get("/steward").text
    assert 'data-testid="agreement-figure"' in body
    # Three recommendations were prepared and none of them was accepted yet.
    counts = re.search(
        r'data-testid="agreement-counts">\s*([^<]+)<', body
    )
    assert counts is not None, body[:400]
    assert "0 accepted unchanged of 4 prepared in the last 7 days" in counts.group(1)


def test_the_figure_rises_when_a_recommendation_is_accepted(
    client: TestClient, environment: Settings
) -> None:
    """An accepted recommendation is part of the agreement."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    post(client, "steward.assist.prepare", {"next": "/steward"}, "/steward")
    # The steward accepts one recommendation of the queue.
    queue = client.get("/steward").text
    hrefs = re.findall(r'href="(/steward/issues/link/[^"]+)"', queue)
    assert hrefs
    path = hrefs[0]
    identifier = re.search(
        r'name="recommendation_id" value="([^"]+)"', client.get(path).text
    )
    assert identifier is not None
    post(
        client,
        "steward.assist.accept",
        {"recommendation_id": identifier.group(1), "next": path},
        path,
    )
    body = client.get("/steward").text
    counts = re.search(r'data-testid="agreement-counts">\s*([^<]+)<', body)
    assert counts is not None, body[:400]
    assert "1 accepted unchanged of 4 prepared in the last 7 days" in counts.group(1)
    share = re.search(r'data-testid="agreement-share">([^<]+)<', body)
    assert share is not None
    assert share.group(1).strip() == "25%"


def test_a_reason_the_steward_wrote_is_not_agreement(
    client: TestClient, environment: Settings
) -> None:
    """A recommendation the steward rewrote does not raise the figure."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    post(client, "steward.assist.prepare", {"next": "/steward"}, "/steward")
    queue = client.get("/steward").text
    hrefs = re.findall(r'href="(/steward/issues/link/[^"]+)"', queue)
    assert hrefs
    path = hrefs[0]
    identifier = re.search(
        r'name="recommendation_id" value="([^"]+)"', client.get(path).text
    )
    assert identifier is not None
    post(
        client,
        "steward.assist.accept",
        {
            "recommendation_id": identifier.group(1),
            "reason": "My independent assessment replaces the assistant reason.",
            "next": path,
        },
        path,
    )
    body = client.get("/steward").text
    counts = re.search(r'data-testid="agreement-counts">\s*([^<]+)<', body)
    assert counts is not None, body[:400]
    assert "0 accepted unchanged of 4 prepared in the last 7 days" in counts.group(1)
    share = re.search(r'data-testid="agreement-share">([^<]+)<', body)
    assert share is not None
    assert share.group(1).strip() == "0%"
    # The decision recorded the comparison it made when it was taken.
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "steward.recommendation.accept"
                )
            ).scalars().all()
            assert len(events) == 1
            assert (events[0].metadata_json or {}).get("reason_unchanged") is False
    finally:
        factory.dispose()


def test_the_words_muse_wrote_count_as_the_reason_of_the_assistant(
    client: TestClient, environment: Settings
) -> None:
    """The words Muse wrote are the reason of the assistant in other words."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    post(client, "steward.assist.prepare", {"next": "/steward"}, "/steward")
    queue = client.get("/steward").text
    hrefs = re.findall(r'href="(/steward/issues/link/[^"]+)"', queue)
    assert hrefs
    path = hrefs[0]
    identifier = re.search(
        r'name="recommendation_id" value="([^"]+)"', client.get(path).text
    )
    assert identifier is not None
    # The recommendation holds the words Muse wrote for it.
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, identifier.group(1))
            assert row is not None
            row.muse_reason = "The license holder names the same business."
            row.version += 1
    finally:
        factory.dispose()
    # The steward accepts the words Muse wrote.
    post(
        client,
        "steward.assist.accept",
        {
            "recommendation_id": identifier.group(1),
            "reason": "The license holder names the same business.",
            "next": path,
        },
        path,
    )
    body = client.get("/steward").text
    counts = re.search(r'data-testid="agreement-counts">\s*([^<]+)<', body)
    assert counts is not None, body[:400]
    assert "1 accepted unchanged of 4 prepared in the last 7 days" in counts.group(1)
