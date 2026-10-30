"""The demo user switcher: visible label, and each choice lands on that persona's home."""
# REQUIRES: UX-01, PER-04

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

#: persona, expected home path, expected H1 of that home
HOMES = (
    ("persona_applicant", "/city/", "Welcome to the City of Acme"),
    ("persona_data_steward", "/queue", "Work queue"),
    ("persona_permit_reviewer", "/queue", "Work queue"),
    ("persona_city_administrator", "/overview", "Planning overview"),
    ("persona_agent_operator", "/agents", "Agents"),
)


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'switch.db'}",
            "ACME_SECRET_KEY": "demo-switch-test-secret",
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
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def h1(html: str) -> str:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    assert match, "the page has an h1"
    return re.sub(r"<[^>]+>|\s+", " ", match.group(1)).strip()


def test_the_visible_label_and_the_aria_label_are_kept(client: TestClient) -> None:
    client.post("/api/session/select", json={"actor_id": "persona_data_steward"})
    page = client.get("/queue").text
    assert "<span>Demo controls</span>" in page
    assert 'aria-label="Demo controls: switch user"' in page
    assert 'data-testid="demo-switch"' in page
    assert len(re.findall(r"data-demo-persona=", page)) == 5
    assert page.count('action="/ui/actor"') == 5


@pytest.mark.parametrize(("actor_id", "home", "heading"), HOMES)
def test_each_choice_lands_on_that_personas_home(
    client: TestClient, actor_id: str, home: str, heading: str
) -> None:
    client.post("/api/session/select", json={"actor_id": "persona_data_steward"})
    form = re.search(
        rf'<form[^>]*action="/ui/actor"[^>]*>\s*<input type="hidden" name="actor_id" '
        rf'value="{actor_id}">\s*<input type="hidden" name="next" value="([^"]*)">',
        client.get("/queue").text,
    )
    assert form, actor_id
    response = client.post(
        "/ui/actor",
        data={"actor_id": actor_id, "next": form.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.split("?")[0] == home
    landed = client.get(location)
    assert landed.status_code == 200
    assert h1(landed.text) == heading
