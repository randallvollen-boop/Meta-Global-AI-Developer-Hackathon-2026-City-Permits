"""Shared set-up for the P3insight tests: a reset demo, optionally with the synthetic year."""

from __future__ import annotations

from pathlib import Path

from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.synthetic import load_synthetic_year
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

SYNTHETIC_SEED = 20261028
SYNTHETIC_COUNT = 320

ADMIN = "persona_city_administrator"


def build_environment(directory: Path, *, synthetic: bool, name: str = "insight.db") -> Settings:
    """Create and reset a database; load the synthetic year when asked."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{directory / name}",
            "ACME_SECRET_KEY": "insight-test-secret-value",
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
        if synthetic:
            with transaction(factory) as session:
                load_synthetic_year(session, seed=SYNTHETIC_SEED, count=SYNTHETIC_COUNT)
    finally:
        factory.dispose()
    return settings


def open_factory(settings: Settings) -> SessionFactory:
    return SessionFactory(settings.database_url)
