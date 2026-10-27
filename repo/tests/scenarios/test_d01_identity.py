"""D01: the main commercial case resolves to one party through decided links.

This scenario covers the registry part of D01: the alias, the unit variation
and the legacy finance identifier reach the same canonical party through
recorded steward decisions.  The exact payment allocation and the issuance
belong to the finance and permit slices and are not exercised here.
"""
# REQUIRES: D01, MDM-01, MDM-02, MDM-03
# The alias, the unit variation and the legacy finance identifier resolve to one
# canonical party only through a recorded steward decision.

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
from acme_city.registry.candidates import generate_candidates
from acme_city.registry.provenance import current_accepted_snapshot
from acme_city.registry.schemas import MatchDecisionCommand, MatchProposalCommand
from acme_city.registry.service import RegistryService


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'd01.db'}",
            "ACME_SECRET_KEY": "d01-scenario-secret-value",
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


def approve(session, source_system_id: str, dataset_key: str, record_id: str) -> None:
    """Propose and approve one source link."""
    service = RegistryService(session)
    service.propose(
        MatchProposalCommand(
            source_system_id=source_system_id,
            dataset_key=dataset_key,
            source_record_id=record_id,
        ),
        steward(),
    )
    service.decide(
        MatchDecisionCommand(
            source_system_id=source_system_id,
            source_record_id=record_id,
            decision="approve",
            reason="fictional demonstration: the evidence names the same party",
            evidence=[
                {
                    "field": "declared reference",
                    "value": record_id,
                    "note": "the steward compared the declared reference with the registry",
                }
            ],
        ),
        steward(),
    )


def test_the_alias_reaches_the_recorded_party(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RegistryService(session)
            proposal = service.propose(
                MatchProposalCommand(
                    source_system_id="permitting",
                    dataset_key="applicant_profiles",
                    source_record_id="PER-AP-0003",
                ),
                steward(),
            )
            assert proposal.disposition == "supported"
            assert proposal.candidate_ids == ["party_cedarline"]
            methods = {item.method for item in proposal.supporting_evidence}
            assert "alias_normalized_exact" in methods
    finally:
        factory.dispose()


def test_the_unit_variation_resolves_to_the_same_official_address(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            snapshot = current_accepted_snapshot(
                session, "permitting", "applications_and_permits", "PER-APP-SYN-APP-001"
            )
            assert snapshot is not None
            result = generate_candidates(
                session,
                dict(snapshot.raw_payload or {}),
                "party",
                snapshot.source_snapshot_id,
            )
            by_entity = {candidate.entity_id: candidate for candidate in result.candidates}
            assert "party_cedarline" in by_entity
            details = " ".join(item.detail for item in by_entity["party_cedarline"].supporting)
            assert "official address" in details
            assert not by_entity["party_cedarline"].conflicting
    finally:
        factory.dispose()


def test_the_legacy_finance_identifier_reaches_the_same_party(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            approve(session, "erp_finance", "finance_accounts", "ERP-ACC-77120-LEG")
            account = session.execute(
                select(registry.FinanceAccount).where(
                    registry.FinanceAccount.source_account_id == "ERP-ACC-77120-LEG"
                )
            ).scalar_one()
            assert account.party_id == "party_cedarline"
            assert account.link_status == "linked"
            assert account.link_decision
    finally:
        factory.dispose()


def test_the_decided_links_share_one_canonical_party(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            approve(session, "permitting", "applicant_profiles", "PER-AP-0003")
            approve(session, "erp_finance", "business_licensing_register", "ERP-BL-00412")
            approve(session, "erp_finance", "finance_accounts", "ERP-ACC-88231")
            approve(session, "permitting", "contractor_register", "PER-CR-00188")

            rows = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.link_status == "approved"
                )
            ).scalars().all()
            cedarline_links = [row for row in rows if row.entity_id == "party_cedarline"]
            assert len(cedarline_links) == 3
            for row in cedarline_links:
                assert row.decision_actor_id == "persona_data_steward"
                assert row.decided_at is not None
                assert row.decision
            assert {row.source_record_id for row in cedarline_links} == {
                "PER-AP-0003",
                "ERP-BL-00412",
                "ERP-ACC-88231",
            }
            assert {row.entity_id for row in rows} == {"party_cedarline", "party_ironvale"}
    finally:
        factory.dispose()
