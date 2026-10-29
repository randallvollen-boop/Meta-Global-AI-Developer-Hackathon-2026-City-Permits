"""Shared fixtures for the security-audit regression tests (fictional ACME data)."""

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


@pytest.fixture()
def audit_settings(tmp_path: Path) -> Settings:
    """Settings for a seeded demo database in a temporary directory."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'audit.db'}",
            "ACME_SECRET_KEY": "audit-regression-secret-value",
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
def audit_client(audit_settings: Settings):
    with TestClient(create_app(audit_settings)) as client:
        yield client


@pytest.fixture()
def pick():
    """Return a function that selects a demonstration persona on a client."""

    def _pick(client: TestClient, actor_id: str) -> None:
        response = client.post("/api/session/select", json={"actor_id": actor_id})
        assert response.status_code == 200, response.text

    return _pick
