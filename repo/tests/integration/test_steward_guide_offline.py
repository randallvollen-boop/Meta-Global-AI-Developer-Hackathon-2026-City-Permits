"""The rendered steward guide always uses saved guidance.

Fictional ACME City data only.
"""

from __future__ import annotations

import sys
import types
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return a hosted-mode client whose Muse imports fail if reached."""
    class RaisingMuse(types.ModuleType):
        def __getattr__(self, name: str):
            raise AssertionError(f"rendered guide reached Muse: {name}")

    monkeypatch.setitem(sys.modules, "acme_city.muse.client", RaisingMuse("acme_city.muse.client"))
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'guide.db'}",
            "ACME_SECRET_KEY": "guide-offline-secret-value",
            # The hosted demonstration: the demo deployment with the public
            # demonstration on.  Never the production mode.
            "ACME_DEPLOYMENT_MODE": "demo",
            "ACME_PUBLIC_DEMO": "1",
        },
        key_file=tmp_path / "missing.env",
    )
    # No provider key: the guide must answer without one.
    assert settings.meta_api_key is None
    initialize_database(settings)
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            bundle = FixtureBundle.load()
            session.add(DemoEnvironment(id="demo_environment_local", environment_id=ENVIRONMENT_ID, fictional_demo=True, fixture_version=bundle.fixture_version, label="local fictional demonstration"))
            # The session does not autoflush, so the marker has to reach the
            # database before the reset looks for it.
            session.flush()
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
            seed_cedarline(session)
    finally:
        factory.dispose()
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        assert test_client.post("/api/session/select", json={"actor_id": "persona_data_steward"}).status_code == 200
        yield test_client


@pytest.mark.parametrize("screen", ("queue", "case", "profile"))
def test_guide_is_saved_and_repeatable_without_muse(client: TestClient, screen: str) -> None:
    """Queue, case, and profile render the same saved guide twice in hosted mode."""
    path = "/steward" if screen == "queue" else "/masters/party_cedarline"
    if screen == "case":
        queue = client.get("/steward").text
        match = re.search(r'href="(/steward/issues/link/[^\"]+)', queue)
        assert match is not None
        path = match.group(1).replace("&amp;", "&")
    first = client.get(path)
    second = client.get(path)
    assert first.status_code == second.status_code == 200
    marker = 'data-testid="steward-guide-answer">'
    first_answer = first.text.split(marker, 1)[1].split("</p>", 1)[0]
    second_answer = second.text.split(marker, 1)[1].split("</p>", 1)[0]
    assert first_answer == second_answer
    assert "Saved guidance. Live Muse is off." in first.text
