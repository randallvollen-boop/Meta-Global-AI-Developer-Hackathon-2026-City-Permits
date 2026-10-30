"""The button of Muse on the task page of the Data Steward.

Without a credential and with the provider off, the button is disabled and a
short note says why.  With a credential the steward may press it: Muse
rewrites the reason in plain words and changes neither the decision nor the
certainty of the recommendation.

The provider is a fake transport: no test here makes an outside call.

Fictional ACME City data only.
"""
# REQUIRES: AI-02, AI-03, UX-01, PER-04

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.agents import steward_explain
from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.muse.client import MuseClient
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

CREDENTIAL = "test-muse-explanation-key-not-a-real-credential"


class FakeTransport(httpx.BaseTransport):
    """A transport that answers with a fixed body."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200,
            json={"id": "resp_explain", "status": "completed", "output_text": self.body},
        )


def build_environment(tmp_path: Path, **extra: str) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'steward-explain-ui.db'}",
            "ACME_SECRET_KEY": "steward-explain-ui-secret-value",
            **extra,
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
def environment(tmp_path: Path) -> Settings:
    return build_environment(tmp_path)


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


def case_path(client: TestClient) -> str:
    """Return the address of the focused case of one source record."""
    queue = client.get("/steward?filter=needs_review").text
    hrefs = re.findall(r'href="(/steward/issues/link/[^"]+)"', queue)
    assert hrefs
    return hrefs[0]


def explain_button(client: TestClient, path: str) -> str:
    """Return the markup of the button of Muse."""
    body = client.get(path).text
    button = re.search(r'<button[^>]*data-testid="assistant-explain"[^>]*>', body)
    assert button is not None, body[:400]
    return button.group(0)


def prepare(client: TestClient, path: str) -> str:
    """Prepare the recommendation of one task and return its identifier."""
    response = post(
        client,
        "steward.assist.recommend",
        {"task_kind": "link", "task_id": path.split("?")[0].rsplit("/", 1)[-1], "next": path},
        path,
    )
    assert response.status_code == 200, response.text
    body = client.get(path).text
    identifier = re.search(r'name="recommendation_id" value="([^"]+)"', body)
    assert identifier is not None
    return identifier.group(1)


def test_the_button_is_off_without_a_credential(
    client: TestClient, environment: Settings
) -> None:
    """Without a credential the button is off and the note says why."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    path = case_path(client)
    prepare(client, path)
    button = explain_button(client, path)
    assert "disabled" in button
    body = client.get(path).text
    assert 'data-testid="assistant-explain-note"' in body
    assert "No provider credential is configured" in body


def test_the_button_is_off_when_the_provider_is_disabled(tmp_path: Path) -> None:
    """With the provider off the button is off and the note says why."""
    environment = build_environment(
        tmp_path, META_API_KEY=CREDENTIAL, ACME_MUSE_PROVIDER_ENABLED="false"
    )
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as client:
        wake_the_assistant(client)
        choose(client, "persona_data_steward")
        path = case_path(client)
        prepare(client, path)
        button = explain_button(client, path)
        assert "disabled" in button
        body = client.get(path).text
        assert "Live Muse is off in this deployment" in body


def test_muse_rewrites_the_reason_and_changes_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The words come from Muse; the decision and the certainty do not."""
    environment = build_environment(tmp_path, META_API_KEY=CREDENTIAL)
    transport = FakeTransport(json.dumps({"explanation": "The licence names the same business."}))
    monkeypatch.setattr(
        steward_explain,
        "MuseClient",
        lambda settings, **kwargs: MuseClient(settings, transport=transport, **kwargs),
    )
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as client:
        wake_the_assistant(client)
        choose(client, "persona_data_steward")
        path = case_path(client)
        identifier = prepare(client, path)
        button = explain_button(client, path)
        assert "disabled" not in button
        response = post(
            client,
            "steward.assist.explain",
            {"recommendation_id": identifier, "next": path},
            path,
        )
        assert response.status_code == 200, response.text
        assert "rewrote" in response.json()["message"]
        body = client.get(path).text
        assert 'data-testid="assistant-muse-reason"' in body
        assert "The licence names the same business." in body
        # The reason the steward sends is prefilled with the plain words.
        field = re.search(
            r'<textarea[^>]*data-testid="assistant-reason-field"[^>]*>(.*?)</textarea>',
            body,
            re.S,
        )
        assert field is not None
        assert field.group(1).strip() == "The licence names the same business."

    assert len(transport.requests) == 1
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.get(StewardRecommendation, identifier)
            assert row is not None
            # The decision of the City did not change.
            assert row.outcome == "confirm"
            assert row.confidence == "high"
            assert row.muse_run_id
    finally:
        factory.dispose()
