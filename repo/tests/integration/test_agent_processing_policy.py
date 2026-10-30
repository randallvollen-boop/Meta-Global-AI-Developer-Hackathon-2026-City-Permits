"""The reset seeds one manual processing policy without changing fixtures."""

from __future__ import annotations

from pathlib import Path

from acme_city.agents.policy import current_policy
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction


def test_reset_seeds_the_manual_processing_policy(tmp_path: Path) -> None:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'processing-policy.db'}",
            "ACME_SECRET_KEY": "processing-policy-test-secret",
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
        with factory() as session:
            policy = current_policy(session)
            assert policy is not None
            assert (policy.mode, policy.runs_per_hour, policy.max_batch_size) == ("manual", 60, 20)
    finally:
        factory.dispose()
