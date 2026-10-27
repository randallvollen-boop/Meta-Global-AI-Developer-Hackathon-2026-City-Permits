"""D03: the expired contractor credential stays visible and blocks its dependent.

The registry reports the credential as the source stated it: expired.  The
dependent permit action is blocked by the permit slice; the registry keeps the
credential state visible so that the blocker has a declared cause.
"""
# REQUIRES: D03, MDM-04, CHG-03
# The credential state of a party comes from the authoritative source and is
# never presented as active while the source says it expired.

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.registry.schemas import MatchDecisionCommand, MatchProposalCommand
from acme_city.registry.service import RegistryService


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'd03.db'}",
            "ACME_SECRET_KEY": "d03-scenario-secret-value",
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


def test_the_expired_credential_is_reported_with_its_status(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RegistryService(session)
            proposal = service.propose(
                MatchProposalCommand(
                    source_system_id="permitting",
                    dataset_key="contractor_register",
                    source_record_id="PER-CR-00977",
                ),
                steward(),
            )
            assert proposal.candidate_ids == ["party_halcyon"]
            credential_evidence = [
                item
                for item in proposal.supporting_evidence
                if item.method == "credential_exact"
            ]
            assert credential_evidence
            assert "expired" in credential_evidence[0].detail
            assert "CR-2025-00977" in credential_evidence[0].detail
    finally:
        factory.dispose()


def test_the_trusted_view_shows_the_expired_registration(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = RegistryService(session)
            service.propose(
                MatchProposalCommand(
                    source_system_id="permitting",
                    dataset_key="contractor_register",
                    source_record_id="PER-CR-00977",
                ),
                steward(),
            )
            service.decide(
                MatchDecisionCommand(
                    source_system_id="permitting",
                    source_record_id="PER-CR-00977",
                    decision="approve",
                    reason="the registration number and the holder name agree",
                    evidence=[
                        {
                            "field": "registration_number",
                            "value": "CR-2025-00977",
                            "note": "the credential is expired, which the steward recorded",
                        }
                    ],
                ),
                steward(),
            )
            view = RegistryService(session).trusted_view("party_halcyon")
            assert view is not None
            fields = {field.attribute_path: field for field in view.fields}
            status = fields["contractor_registration_status"]
            assert status.state == "authoritative"
            assert status.value == "expired"
            assert status.authority_policy_id == "authority_contractor"
    finally:
        factory.dispose()


def test_the_credential_record_keeps_its_own_validity_window(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            credential = session.execute(
                select(registry.Credential).where(
                    registry.Credential.number == "CR-2025-00977"
                )
            ).scalar_one()
            assert credential.status == "expired"
            assert credential.valid_from is not None
            assert credential.valid_to is not None
            assert credential.valid_to > credential.valid_from
            assert credential.holder_party_id == "party_halcyon"
    finally:
        factory.dispose()
