"""The Agent Operator home and its four navigation destinations."""

from __future__ import annotations

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


@pytest.fixture()
def client(tmp_path: Path):
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
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        assert test_client.post("/api/session/select", json={"actor_id": "persona_agent_operator"}).status_code == 200
        yield test_client


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
