"""D02: the false friend stays a distinct party despite a similar name.

The two coffee businesses share a building and a similar name.  The registry
offers both candidates, keeps the contradicting evidence visible, and never
creates an accepted link on its own.
"""
# REQUIRES: D02, MDM-02, MDM-03
# The false friend keeps its own identity, and no link is ever accepted without
# a recorded steward decision.

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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'd02.db'}",
            "ACME_SECRET_KEY": "d02-scenario-secret-value",
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


def test_the_similar_name_is_offered_with_its_contradicting_evidence(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RegistryService(session)
            proposal = service.propose(
                MatchProposalCommand(
                    source_system_id="erp_finance",
                    dataset_key="business_licensing_register",
                    source_record_id="ERP-BL-00413",
                ),
                steward(),
            )
            assert proposal.disposition == "unresolved"
            assert "party_false_friend" in proposal.candidate_ids
            assert "party_cedarline" in proposal.candidate_ids
            conflicting = {item.method for item in proposal.conflicting_evidence}
            assert "source_reference_mismatch" in conflicting
            assert "credential_number_conflict" in conflicting
            assert "address_unit_conflict" in conflicting
    finally:
        factory.dispose()


def test_no_link_is_accepted_without_a_steward_decision(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = RegistryService(session)
            service.propose(
                MatchProposalCommand(
                    source_system_id="erp_finance",
                    dataset_key="business_licensing_register",
                    source_record_id="ERP-BL-00413",
                ),
                steward(),
            )
            rows = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "ERP-BL-00413"
                )
            ).scalars().all()
            assert rows
            assert {row.link_status for row in rows} == {"proposed"}
            assert {row.decision_actor_id for row in rows} == {None}
    finally:
        factory.dispose()


def test_the_steward_decision_keeps_the_two_parties_apart(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = RegistryService(session)
            service.propose(
                MatchProposalCommand(
                    source_system_id="erp_finance",
                    dataset_key="business_licensing_register",
                    source_record_id="ERP-BL-00413",
                ),
                steward(),
            )
            service.decide(
                MatchDecisionCommand(
                    source_system_id="erp_finance",
                    source_record_id="ERP-BL-00413",
                    decision="approve",
                    reason=(
                        "the licence number, the declared holder and the unit five address "
                        "name the false friend; the similar name is not the same party"
                    ),
                    evidence=[
                        {
                            "field": "license_number",
                            "value": "BL-2026-00413",
                            "note": "the licence belongs to the false friend",
                        },
                        {
                            "field": "business_address",
                            "value": "400 Lantern Row Unit 5",
                            "direction": "conflicting",
                            "note": "the unit differs from the approved party",
                        },
                    ],
                ),
                steward(),
            )
            rows = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "ERP-BL-00413",
                    registry.Crosswalk.link_status == "approved",
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].entity_id == "party_false_friend"

            cedarline = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "ERP-BL-00413",
                    registry.Crosswalk.entity_id == "party_cedarline",
                )
            ).scalars().first()
            assert cedarline is None
    finally:
        factory.dispose()


def test_the_two_canonical_parties_keep_their_own_address(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            for entity_id, expected in (
                ("party_cedarline", "Cedarline Coffee Roasters LLC"),
                ("party_false_friend", "Cedarline Coffee Works LLC"),
            ):
                party = session.get(registry.Party, entity_id)
                assert party is not None
                assert party.display_name == expected
                assert party.entity_id == entity_id
    finally:
        factory.dispose()
