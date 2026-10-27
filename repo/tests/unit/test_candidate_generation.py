"""Candidate generation tests: evidence, near misses and explicit no-match."""

from __future__ import annotations

from pathlib import Path

import pytest

from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.registry.candidates import generate_candidates
from acme_city.registry.provenance import current_accepted_snapshot

SOURCE_OF_DATASET = {
    "applicant_profiles": "permitting",
    "applications_and_permits": "permitting",
    "contractor_register": "permitting",
    "parcel_register": "gis",
    "address_register": "gis",
    "business_licensing_register": "erp_finance",
    "finance_accounts": "erp_finance",
}


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'candidates.db'}",
            "ACME_SECRET_KEY": "candidate-test-secret-value",
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


def candidates_for(settings: Settings, dataset_key: str, record_id: str, entity_type: str):
    """Return the candidate set of one seeded source record."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            snapshot = current_accepted_snapshot(
                session, SOURCE_OF_DATASET[dataset_key], dataset_key, record_id
            )
            assert snapshot is not None, f"{dataset_key}/{record_id} has no accepted snapshot"
            return generate_candidates(
                session,
                dict(snapshot.raw_payload or {}),
                entity_type,
                snapshot.source_snapshot_id,
            )
    finally:
        factory.dispose()


def test_the_main_case_proposes_one_supported_candidate(seeded: Settings) -> None:
    result = candidates_for(seeded, "applicant_profiles", "PER-AP-0003", "party")
    assert result.disposition == "supported"
    assert [candidate.entity_id for candidate in result.candidates] == ["party_cedarline"]
    methods = {item.method for item in result.candidates[0].supporting}
    assert "source_reference_exact" in methods
    assert "alias_normalized_exact" in methods
    assert result.candidates[0].conflicting == ()


def test_the_false_friend_keeps_its_conflicting_evidence(seeded: Settings) -> None:
    result = candidates_for(seeded, "business_licensing_register", "ERP-BL-00413", "party")
    assert result.disposition == "unresolved"
    by_entity = {candidate.entity_id: candidate for candidate in result.candidates}
    assert "party_false_friend" in by_entity
    near_miss = by_entity["party_cedarline"]
    conflicting = {item.method for item in near_miss.conflicting}
    assert "source_reference_mismatch" in conflicting
    assert "credential_number_conflict" in conflicting
    assert "address_unit_conflict" in conflicting


def test_a_shared_address_alone_keeps_no_candidate(seeded: Settings) -> None:
    """A party that only shares the building is not offered as a candidate."""
    result = candidates_for(seeded, "business_licensing_register", "ERP-BL-00412", "party")
    assert [candidate.entity_id for candidate in result.candidates] == ["party_cedarline"]


def test_an_unknown_parcel_has_no_candidate(seeded: Settings) -> None:
    result = candidates_for(
        seeded, "applications_and_permits", "PER-APP-SYN-APP-004", "parcel"
    )
    assert result.disposition == "no_match"
    assert result.candidates == ()


def test_an_official_parcel_is_matched_by_its_identifier(seeded: Settings) -> None:
    result = candidates_for(seeded, "parcel_register", "GIS-PCL-1001", "parcel")
    assert result.disposition == "supported"
    assert [candidate.entity_id for candidate in result.candidates] == ["parcel_1001"]


def test_an_official_address_is_matched_with_its_unit(seeded: Settings) -> None:
    result = candidates_for(seeded, "address_register", "GIS-AD-0400-U2", "address")
    assert result.disposition == "supported"
    assert [candidate.entity_id for candidate in result.candidates] == [
        "address_400_lantern_unit_2"
    ]


def test_the_legacy_finance_account_carries_its_holder_evidence(seeded: Settings) -> None:
    result = candidates_for(seeded, "finance_accounts", "ERP-ACC-77120-LEG", "party")
    assert result.disposition == "supported"
    assert [candidate.entity_id for candidate in result.candidates] == ["party_cedarline"]
    methods = {item.method for item in result.candidates[0].supporting}
    assert "legacy_account_same_holder" in methods


def test_the_score_is_an_uncalibrated_ordering_measure(seeded: Settings) -> None:
    result = candidates_for(seeded, "business_licensing_register", "ERP-BL-00412", "party")
    score = result.best.score
    assert score is not None
    assert 0.0 <= score <= 1.0
    assert result.method == "deterministic"


def test_a_name_alone_never_reaches_a_supported_disposition(seeded: Settings) -> None:
    """A record whose own reference names nobody keeps its near miss unresolved."""
    from acme_city.ingestion.schemas import IngestCommand, SourceRecordCommand
    from acme_city.ingestion.service import IngestionService
    from acme_city.auth.context import ActorContext

    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = IngestionService(session)
            service.ingest(
                IngestCommand(
                    source_system_id="permitting",
                    dataset_key="applicant_profiles",
                    records=[
                        SourceRecordCommand(
                            source_record_id="PER-AP-9001",
                            source_record_version="1",
                            payload={
                                "party_ref": "party_not_in_the_registry",
                                "organization_name": "Cedar Line Coffee Roasters",
                                "contact_email": "unknown@example.invalid",
                                "contact_phone": "+1-555-0999",
                                "preferred_contact": "email",
                            },
                        )
                    ],
                ),
                ActorContext(actor_id="persona_data_steward"),
            )
    finally:
        factory.dispose()

    result = candidates_for(seeded, "applicant_profiles", "PER-AP-9001", "party")
    assert result.disposition == "unresolved"
    by_entity = {candidate.entity_id: candidate for candidate in result.candidates}
    assert "party_cedarline" in by_entity
    conflicting = {item.method for item in by_entity["party_cedarline"].conflicting}
    assert "source_reference_mismatch" in conflicting
