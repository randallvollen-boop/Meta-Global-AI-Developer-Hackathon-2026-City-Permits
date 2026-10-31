"""The administration screen without a live provider.

The appearance tab shows the icon the City uses, the saved icons of a permit
type and, last, the generation.  When the provider is off the tab says so in
plain words, keeps the saved icons usable and refuses the generation before a
provider client is built: no request leaves the process and no generation
attempt is recorded.
"""
# REQUIRES: AI-01, AI-03, UX-01
# The appearance tab is honest about the provider: it disables the generation
# it cannot make, keeps the saved icons and never reaches the network.

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import audit, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.ui.router import router as ui_router

ADMIN = "persona_city_administrator"


class TripwireTransport(httpx.BaseTransport):
    """A transport that records every call and fails it."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        raise httpx.ConnectError("the tripwire transport must never be reached")


@pytest.fixture()
def tripwire(monkeypatch: pytest.MonkeyPatch) -> TripwireTransport:
    """Make the default httpx transport the tripwire."""
    stub = TripwireTransport()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", stub.handle_request)
    return stub


@pytest.fixture()
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Return the settings of a deployment whose provider is switched off.

    The environment variables are the ones the running process reads, so the
    screen and the server agree about the provider.
    """
    monkeypatch.setenv("ACME_MUSE_PROVIDER_ENABLED", "0")
    monkeypatch.setenv("ACME_PUBLIC_DEMO", "0")
    monkeypatch.setenv("ACME_MUSE_LIVE_CALLS_ALLOWED", "0")
    monkeypatch.setenv("ACME_KEY_FILE", str(tmp_path / "missing.env"))
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'offline-presentation.db'}",
            "ACME_SECRET_KEY": "offline-presentation-secret-value",
            "ACME_MUSE_PROVIDER_ENABLED": "0",
            "ACME_PUBLIC_DEMO": "0",
            "ACME_MUSE_LIVE_CALLS_ALLOWED": "0",
        },
        key_file=tmp_path / "missing.env",
    )
    assert settings.provider_enabled is False
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
def client(environment: Settings) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str = ADMIN) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def csrf_of(client: TestClient, path: str) -> str:
    page = client.get(path)
    assert page.status_code == 200, path
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match, path
    return match.group(1)


def test_the_appearance_tab_says_that_the_generation_is_off(client: TestClient) -> None:
    choose(client)
    page = client.get("/admin?tab=appearance")
    assert page.status_code == 200, page.text[:400]
    assert "Live Muse generation is off." in page.text
    # Changed deliberately (demo polish, AD1): the notice is one line now, so
    # the second sentence is gone and the reason follows the first one.
    assert "You can preview and use saved icons." not in page.text
    assert 'data-testid="icon-generation-unavailable"' in page.text
    assert "external AI provider calls are disabled" in page.text


def test_the_saved_icons_stay_usable_while_the_generation_is_off(
    client: TestClient,
) -> None:
    choose(client)
    page = client.get("/admin?tab=appearance")
    assert page.text.count('data-testid="permit-type-icon-row"') == 17
    assert 'data-testid="permit-type-current-icon"' in page.text
    assert 'data-testid="icon-save-form"' in page.text
    assert 'data-testid="icon-save"' in page.text
    assert 'data-testid="icon-thumb"' in page.text
    assert 'data-testid="icon-history"' in page.text
    # The generation is still on the page, and it is disabled with a reason.
    assert 'data-testid="icon-generate-form"' in page.text
    assert 'data-testid="icon-generate" disabled' in page.text
    assert 'data-testid="icon-generate-unavailable"' in page.text


def test_a_bundled_icon_is_not_called_a_muse_generation(client: TestClient) -> None:
    choose(client)
    page = client.get("/admin?tab=appearance")
    # The seeded assets are bundled seed assets, and the screen says so.
    assert "Bundled seed asset" in page.text
    row = page.text.split('data-testid="permit-type-icon-row"', 1)[1]
    assert "Muse Image generation" not in row.split("</article>", 1)[0]


def test_the_generation_is_refused_without_a_provider_call(
    client: TestClient, tripwire: TripwireTransport, environment: Settings
) -> None:
    choose(client)
    token = csrf_of(client, "/admin?tab=appearance")
    response = client.post(
        "/ui/actions/permit.icon.generate",
        data={
            "csrf_token": token,
            "action_id": "permit.icon.generate",
            "next": "/admin?tab=appearance",
            "permit_type_id": "permit_type_deck_fence",
            "prompt": "a wooden deck with a fence",
            "expected_version": "1",
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert "off" in response.json()["message"]
    assert tripwire.calls == []
    # A refused generation is not a generation attempt.
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            attempts = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "ui.permit.icon.generate"
                )
            ).scalars().all()
            assert all(row.outcome == "denied" for row in attempts)
            icons = session.execute(select(permit.PermitTypeIcon)).scalars().all()
            assert {row.source for row in icons} == {"seed"}
    finally:
        factory.dispose()


def test_a_saved_icon_is_still_saved_while_the_generation_is_off(
    client: TestClient, environment: Settings
) -> None:
    choose(client)
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.execute(
                select(permit.PermitType).where(
                    permit.PermitType.id == "permit_type_deck_fence"
                )
            ).scalar_one()
            icon_id = row.icon_id
            version = row.version
    finally:
        factory.dispose()
    assert icon_id
    token = csrf_of(client, "/admin?tab=appearance")
    response = client.post(
        "/ui/actions/permit.icon.save",
        data={
            "csrf_token": token,
            "action_id": "permit.icon.save",
            "next": "/admin?tab=appearance",
            "permit_type_id": "permit_type_deck_fence",
            "icon_id": icon_id,
            "expected_version": str(version),
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200, response.text
    with factory() as session:
        row = session.execute(
            select(permit.PermitType).where(
                permit.PermitType.id == "permit_type_deck_fence"
            )
        ).scalar_one()
        assert row.icon_id == icon_id
        assert row.version == version + 1


def test_the_generation_is_offered_when_the_provider_may_be_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deployment with a provider and a credential may generate an icon."""
    monkeypatch.setenv("ACME_KEY_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("META_API_KEY", "test-credential-not-a-real-credential")
    monkeypatch.setenv("ACME_MUSE_PROVIDER_ENABLED", "1")
    monkeypatch.setenv("ACME_PUBLIC_DEMO", "0")
    monkeypatch.setenv("ACME_MUSE_LIVE_CALLS_ALLOWED", "1")
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'online-presentation.db'}",
            "ACME_SECRET_KEY": "online-presentation-secret-value",
            "META_API_KEY": "test-credential-not-a-real-credential",
            "ACME_MUSE_PROVIDER_ENABLED": "1",
            "ACME_PUBLIC_DEMO": "0",
            "ACME_MUSE_LIVE_CALLS_ALLOWED": "1",
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
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as client:
        choose(client)
        page = client.get("/admin?tab=appearance")
        assert page.status_code == 200
        assert "Live Muse generation is off." not in page.text
        assert 'data-testid="icon-generate" disabled' not in page.text
        assert 'data-testid="icon-generate-unavailable"' not in page.text
