"""D04: the unknown parcel stays unresolved and no parcel is invented.

An application cites a parcel number that the official register does not hold.
The registry reports an explicit no-match, keeps the application site
unresolved, and creates no parcel of its own.
"""
# REQUIRES: D04, MDM-03, CHG-03
# An unknown parcel is never invented, and the record that cites it stays
# unresolved with an explicit no-match.

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import permit, registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.registry.schemas import MatchProposalCommand
from acme_city.registry.service import RegistryService


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'd04.db'}",
            "ACME_SECRET_KEY": "d04-scenario-secret-value",
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


def steward() -> ActorContext:
    """Return the acting context of the data steward."""
    return ActorContext(actor_id="persona_data_steward")


def test_an_unknown_parcel_has_an_explicit_no_match(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RegistryService(session)
            proposal = service.propose(
                MatchProposalCommand(
                    source_system_id="permitting",
                    dataset_key="applications_and_permits",
                    source_record_id="PER-APP-SYN-APP-004",
                    entity_type="parcel",
                ),
                steward(),
            )
            assert proposal.disposition == "no_match"
            assert proposal.candidate_ids == []
            assert proposal.entity_id is None
    finally:
        factory.dispose()


def test_no_parcel_is_invented_for_the_unknown_number(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            parcels = session.execute(select(registry.Parcel)).scalars().all()
            numbers = {parcel.source_parcel_number for parcel in parcels}
            assert "ACME-P-9999" not in numbers
            assert numbers == {"ACME-P-1001", "ACME-P-1002"}

            entities = session.execute(
                select(registry.CanonicalEntity).where(
                    registry.CanonicalEntity.entity_type == "parcel"
                )
            ).scalars().all()
            assert entities == []
    finally:
        factory.dispose()


def test_the_application_that_cites_the_unknown_parcel_stays_unresolved(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            site = session.execute(
                select(permit.ApplicationSite).where(
                    permit.ApplicationSite.application_id == "app_d04"
                )
            ).scalar_one()
            assert site.resolution_status == "unresolved"
            assert site.parcel_id is None
            assert site.address_id is None
            assert site.submitted_address_text == "1234 Kestrel Pass, ACME City"

            application = session.get(permit.Application, "app_d04")
            assert application is not None
            assert application.submitted_facts["submitted_parcel"] == "ACME-P-9999"
    finally:
        factory.dispose()
