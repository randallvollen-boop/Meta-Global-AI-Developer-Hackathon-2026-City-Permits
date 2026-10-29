"""The client helpers of the HTTP tests, shared by every lane.

Copied from ``tests/integration/test_policy_screens.py``: a reset demo
database, a client with the UI router, ``choose`` to act as one persona and
``csrf_of`` and ``version_of`` to read the form token and the expected version
from a page.  A test module imports the fixtures by name::

    from support.client import client, settings  # noqa: F401
"""

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


def build_settings(directory: Path, name: str = "support.db") -> Settings:
    """Create and reset a demo database in ``directory``."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{directory / name}",
            "ACME_SECRET_KEY": "support-test-secret-value",
        },
        key_file=directory / "missing.env",
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


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    return build_settings(tmp_path_factory.mktemp("support"))


@pytest.fixture()
def client(settings):
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> TestClient:
    assert client.post("/api/session/select", json={"actor_id": actor_id}).status_code == 200
    return client


def csrf_of(body: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert match, "the page carries a form token"
    return match.group(1)


def version_of(body: str) -> str:
    match = re.search(r'name="expected_version" value="(\d+)"', body)
    assert match
    return match.group(1)


__all__ = ["build_settings", "choose", "client", "csrf_of", "settings", "version_of"]
