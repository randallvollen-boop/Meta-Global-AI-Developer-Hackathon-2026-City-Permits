"""The readable reference of the City names the same case as the identifier.

The interface shows the reference of an application on every screen, so the
services of the City accept either name: the identifier of the record and
the number the City gave it.
"""
# REQUIRES: PER-01
# A case may be named by its identifier or by its readable reference.

from __future__ import annotations

from pathlib import Path

import pytest

from acme_city.core.config import Settings
from acme_city.core.errors import NotFoundError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.service import PermitService


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'reference.db'}",
            "ACME_SECRET_KEY": "reference-test-secret-value",
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


def test_a_case_may_be_named_by_its_identifier_or_by_its_reference(
    seeded: Settings,
) -> None:
    """Both names open the same case."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            by_id = service.load_application("app_synth_001")
            by_reference = service.load_application("SYN-APP-001")
            assert by_id.id == by_reference.id == "app_synth_001"
    finally:
        factory.dispose()


def test_a_case_that_does_not_exist_is_refused(seeded: Settings) -> None:
    """A name that belongs to no case is refused."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            with pytest.raises(NotFoundError):
                service.load_application("SYN-APP-999")
    finally:
        factory.dispose()
