"""The hosted dispatch lock: no live Muse call leaves a hosted deployment.

The lock sits in the two provider clients.  With a (fake) credential set and a
hosted setting on, a transport stub that fails on any call is never reached by
the agent runs, the icon route or the steward and help pages, and each request
is answered with a handled, non-500 response.  With live calls allowed and a
non-hosted setting the same stub is reached, so the guard is not vacuous.
"""
# REQUIRES: AI-01, AI-03, SEC-01
# The provider boundary refuses to dispatch on the hosted demo, whatever the credential.

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.muse.client import MuseClient, MuseLiveCallBlocked
from acme_city.muse.image_client import MuseImageClient
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.models.model_run import ModelRun
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

CREDENTIAL = "test-hosted-lock-key-not-a-real-credential"


class TripwireTransport(httpx.BaseTransport):
    """A transport stub that records a call and fails it."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        raise httpx.ConnectError("the tripwire transport must never be reached")


def build_settings(tmp_path: Path, **extra: str) -> Settings:
    environ = {
        "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'lock.db'}",
        "ACME_SECRET_KEY": "hosted-lock-secret-value",
        "META_API_KEY": CREDENTIAL,
        **extra,
    }
    return Settings.load(environ=environ, key_file=tmp_path / "missing.env")


def seed(settings: Settings) -> None:
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


@pytest.fixture()
def tripwire(monkeypatch: pytest.MonkeyPatch) -> TripwireTransport:
    """Make the default httpx transport the tripwire, for the HTTP-driven routes."""
    stub = TripwireTransport()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", stub.handle_request)
    return stub


LIVE_FEATURES = {
    "ACME_APPLICANT_ASSIST_LIVE_ENABLED": "true",
    "ACME_POLICY_ASSIST_LIVE_ENABLED": "true",
}
LOCK_TEXT = "locked on the hosted demo"


def client_for(tmp_path: Path, **extra: str):
    settings = build_settings(tmp_path, **LIVE_FEATURES, **extra)
    assert settings.provider_enabled
    assert settings.applicant_assist_live_enabled and settings.policy_assist_live_enabled
    seed(settings)
    app = create_app(settings)
    app.include_router(ui_router)
    client = TestClient(app)
    client.lock_settings = settings  # type: ignore[attr-defined]
    return settings, client


def live_run_errors(client: TestClient) -> list[str]:
    """Return the error text of every live run the application recorded."""
    factory = SessionFactory(client.lock_settings.database_url)  # type: ignore[attr-defined]
    try:
        with factory() as session:
            rows = session.query(ModelRun).filter(ModelRun.mode == "live").all()
            return [row.error or "" for row in rows]
    finally:
        factory.dispose()


@pytest.fixture()
def hosted_client(tmp_path: Path, tripwire: TripwireTransport):
    settings, client = client_for(tmp_path, ACME_PUBLIC_DEMO="true")
    assert settings.public_demo
    with client:
        yield client


@pytest.fixture()
def open_client(tmp_path: Path, tripwire: TripwireTransport):
    """The same live flags with no hosted setting: the lock lets the call through."""
    settings, client = client_for(tmp_path)
    assert not settings.public_demo
    with client:
        yield client


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def csrf_from(client: TestClient, path: str) -> str:
    page = client.get(path)
    assert page.status_code == 200, path
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match, path
    return match.group(1)


def act(client: TestClient, action_id: str, fields: dict[str, Any], next_path: str):
    return client.post(
        f"/ui/actions/{action_id}",
        data={
            "csrf_token": csrf_from(client, next_path),
            "action_id": action_id,
            "next": next_path,
            **fields,
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


def test_the_clients_refuse_to_dispatch_when_hosted(tmp_path: Path) -> None:
    for extra in (
        {"ACME_PUBLIC_DEMO": "true"},
        {
            "ACME_PUBLIC_DEMO": "true",
            "ACME_DEPLOYMENT_MODE": "production",
            "ACME_MUSE_PROVIDER_ENABLED": "true",
        },
    ):
        settings = build_settings(tmp_path, **extra)
        stub = TripwireTransport()
        refused = MuseImageClient(settings, transport=stub).generate("a deck")
        assert refused.ok is False and refused.error
        assert stub.calls == []
        payload = {
            "model": settings.muse_model_allowlist[0],
            "text": {
                "format": {"type": "json_schema", "strict": True, "name": "x", "schema": {}}
            },
            "max_output_tokens": 100,
        }
        with pytest.raises(MuseLiveCallBlocked):
            MuseClient(settings, transport=stub).create_response(payload)
        assert stub.calls == []


def test_the_hosted_lock_names_its_explicit_opt_in(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, ACME_PUBLIC_DEMO="true")
    assert settings.muse_live_calls_allowed is False
    stub = TripwireTransport()
    refused = MuseImageClient(settings, transport=stub).generate("a deck")
    assert refused.ok is False and "ACME_MUSE_LIVE_CALLS_ALLOWED" in (refused.error or "")
    assert stub.calls == []


@pytest.mark.parametrize("extra", [{}, {"ACME_PUBLIC_DEMO": "true", "ACME_MUSE_LIVE_CALLS_ALLOWED": "true"}])
def test_the_stub_is_reached_when_not_hosted_or_explicitly_allowed(tmp_path: Path, extra: dict[str, str]) -> None:
    settings = build_settings(tmp_path, **extra)
    stub = TripwireTransport()
    result = MuseImageClient(settings, transport=stub).generate("a deck")
    assert len(stub.calls) == 1
    assert result.ok is False
    payload = {
        "model": settings.muse_model_allowlist[0],
        "text": {"format": {"type": "json_schema", "strict": True, "name": "x", "schema": {}}},
        "max_output_tokens": 100,
        "input": "a deck",
    }
    stub = TripwireTransport()
    MuseClient(settings, transport=stub).create_response(payload)
    assert len(stub.calls) == 1


def test_the_agent_runs_never_reach_the_provider_when_hosted(
    hosted_client: TestClient, tripwire: TripwireTransport
) -> None:
    choose(hosted_client, "persona_data_steward")
    simulated = hosted_client.post("/api/intake/simulate", json={"scenario": "fence-conforming-rear"})
    assert simulated.status_code == 200, simulated.text
    app_id = simulated.json()["results"][0]["application_id"]
    choose(hosted_client, "persona_city_administrator")
    for key in ("intake", "adjudication"):
        woke = act(hosted_client, "agent.toggle", {"agent_key": key, "mode": "awake"}, f"/agent/{key}")
        assert woke.status_code < 500, woke.text
    choose(hosted_client, "persona_data_steward")
    ran = act(hosted_client, "agent.run.intake", {"application_id": app_id}, "/agent/intake")
    assert ran.status_code < 500, ran.text
    choose(hosted_client, "persona_permit_reviewer")
    ran = act(hosted_client, "agent.run.adjudication", {"application_id": app_id}, "/agent/adjudication")
    assert ran.status_code < 500, ran.text
    assert tripwire.calls == []


def test_the_icon_route_never_reaches_the_provider_when_hosted(
    hosted_client: TestClient, tripwire: TripwireTransport
) -> None:
    choose(hosted_client, "persona_city_administrator")
    response = act(
        hosted_client,
        "permit.icon.generate",
        {"permit_type_id": "permit_type_deck_fence", "prompt": "a wooden deck", "expected_version": "1"},
        "/rules-fees",
    )
    assert response.status_code < 500, response.text
    assert tripwire.calls == []


def ask_help(client: TestClient) -> str:
    choose(client, "persona_applicant")
    response = client.post(
        "/apply/help",
        data={
            "csrf_token": csrf_from(client, "/apply"),
            "question": "How tall may my rear yard fence be?",
            "conversation_version": "0",
            "conversation_id": "",
            "placement": "chooser",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    match = re.search(r"(?:help|conversation)=([^&]+)", response.headers["location"])
    assert match
    return client.get("/apply", params={"help": match.group(1)}).text


def propose_policy(client: TestClient):
    choose(client, "persona_city_administrator")
    return client.post(
        "/policy/propose",
        data={
            "csrf_token": csrf_from(client, "/policy/scenarios"),
            "expected_version": "0",
            "question": "What if the side and rear yard fence limit were 7 ft?",
        },
        follow_redirects=True,
    )


def test_the_help_assistant_is_stopped_by_the_lock_when_hosted(
    hosted_client: TestClient, tripwire: TripwireTransport
) -> None:
    ask_help(hosted_client)
    assert tripwire.calls == []
    errors = live_run_errors(hosted_client)
    assert errors and all(LOCK_TEXT in error for error in errors)


def test_the_policy_assist_is_stopped_by_the_lock_when_hosted(
    hosted_client: TestClient, tripwire: TripwireTransport
) -> None:
    response = propose_policy(hosted_client)
    assert response.status_code < 500, response.text
    assert tripwire.calls == []
    errors = live_run_errors(hosted_client)
    assert errors and all(LOCK_TEXT in error for error in errors)


def test_the_help_route_reaches_the_stub_when_not_hosted(
    open_client: TestClient, tripwire: TripwireTransport
) -> None:
    ask_help(open_client)
    assert len(tripwire.calls) >= 1


def test_the_policy_route_reaches_the_stub_when_not_hosted(
    open_client: TestClient, tripwire: TripwireTransport
) -> None:
    response = propose_policy(open_client)
    assert response.status_code < 500, response.text
    assert len(tripwire.calls) >= 1


def test_the_icon_route_reaches_the_stub_when_not_hosted(
    open_client: TestClient, tripwire: TripwireTransport
) -> None:
    choose(open_client, "persona_city_administrator")
    response = act(
        open_client,
        "permit.icon.generate",
        {"permit_type_id": "permit_type_deck_fence", "prompt": "a wooden deck", "expected_version": "1"},
        "/rules-fees",
    )
    assert response.status_code < 500, response.text
    assert len(tripwire.calls) >= 1


def test_the_steward_and_help_pages_never_reach_the_provider_when_hosted(
    hosted_client: TestClient, tripwire: TripwireTransport
) -> None:
    choose(hosted_client, "persona_data_steward")
    for path in ("/steward", "/help", "/help/tutorial", "/help/how-to"):
        assert hosted_client.get(path).status_code < 500, path
    assert tripwire.calls == []
