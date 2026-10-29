"""Intake tests: idempotency, late versions, staging and the denominators."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.ingestion.schemas import IngestCommand, SourceRecordCommand
from acme_city.ingestion.service import IngestionService
from acme_city.persistence.models import change, registry_automation, source
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)

APPLICANT_PROFILE = {
    "party_ref": "party_applicant_1",
    "display_name": "Tamsin Aldous",
    "contact_email": "t.aldous@example.invalid",
    "contact_phone": "+1-555-0141",
    "preferred_contact": "email",
}


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'ingestion.db'}",
            "ACME_SECRET_KEY": "ingestion-test-secret-value",
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


def steward(session) -> ActorContext:
    """Return the acting context of the data steward."""
    return ActorContext(actor_id="persona_data_steward", role_ids=frozenset())


def command(
    source_system_id: str,
    dataset_key: str,
    records: list[SourceRecordCommand],
    **kwargs: object,
) -> IngestCommand:
    """Return an intake command."""
    return IngestCommand(
        source_system_id=source_system_id,
        dataset_key=dataset_key,
        records=records,
        **kwargs,
    )


def test_an_identical_version_and_payload_is_unchanged(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = IngestionService(session)
            result = service.ingest(
                command(
                    "permitting",
                    "applicant_profiles",
                    [
                        SourceRecordCommand(
                            source_record_id="PER-AP-0001",
                            source_record_version="3",
                            payload=dict(APPLICANT_PROFILE),
                            source_updated_at=datetime(2026, 9, 5, 13, 12, tzinfo=UTC),
                            effective_from=datetime(2026, 9, 5, tzinfo=UTC),
                        )
                    ],
                ),
                steward(session),
            )
            assert result.received == 1
            assert result.unchanged == 1
            assert result.accepted == 0
            assert result.snapshot_ids == ["snap_permitting_PER-AP-0001_v3"]
            snapshots = session.execute(
                select(source.SourceSnapshot).where(
                    source.SourceSnapshot.source_record_id == "PER-AP-0001",
                    source.SourceSnapshot.source_dataset_id == "applicant_profiles",
                )
            ).scalars().all()
            assert len(snapshots) == 1
    finally:
        factory.dispose()


def test_a_changed_version_creates_a_new_immutable_snapshot(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = IngestionService(session)
            payload = dict(APPLICANT_PROFILE)
            payload["contact_email"] = "t.aldous+updated@example.invalid"
            result = service.ingest(
                command(
                    "permitting",
                    "applicant_profiles",
                    [
                        SourceRecordCommand(
                            source_record_id="PER-AP-0001",
                            source_record_version="4",
                            payload=payload,
                            source_updated_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
                        )
                    ],
                ),
                steward(session),
            )
            assert result.accepted == 1
            assert result.unchanged == 0
            snapshots = session.execute(
                select(source.SourceSnapshot)
                .where(
                    source.SourceSnapshot.source_record_id == "PER-AP-0001",
                    source.SourceSnapshot.source_dataset_id == "applicant_profiles",
                )
                .order_by(source.SourceSnapshot.source_record_version)
            ).scalars().all()
            assert [row.source_record_version for row in snapshots] == ["3", "4"]
            assert snapshots[0].raw_payload["contact_email"] == "t.aldous@example.invalid"
            assert snapshots[1].raw_payload["contact_email"] == "t.aldous+updated@example.invalid"
            assert session.execute(select(registry_automation.RegistryAutomationJob)).scalars().all() == []
    finally:
        factory.dispose()


def test_an_older_late_version_is_history_only_and_raises_an_issue(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = IngestionService(session)
            result = service.ingest(
                command(
                    "permitting",
                    "applicant_profiles",
                    [
                        SourceRecordCommand(
                            source_record_id="PER-AP-0001",
                            source_record_version="2",
                            payload={**APPLICANT_PROFILE, "contact_phone": "+1-555-0000"},
                            source_updated_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
                        )
                    ],
                ),
                steward(session),
            )
            assert result.unresolved == 1
            assert result.accepted == 0
            assert result.issue_ids

            current = service.current_accepted_snapshot(
                "permitting", "applicant_profiles", "PER-AP-0001"
            )
            assert current is not None
            assert current.source_record_version == "3"
            assert current.raw_payload["contact_phone"] == "+1-555-0141"

            issues = session.execute(
                select(change.GovernanceIssue).where(
                    change.GovernanceIssue.issue_type == "late_source_version"
                )
            ).scalars().all()
            assert len(issues) == 1
            assert issues[0].status == "open"
    finally:
        factory.dispose()


def test_an_unowned_feed_is_staged_and_never_accepted(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = IngestionService(session)
            result = service.ingest(
                command(
                    "permitting",
                    "unregistered_feeds",
                    [
                        SourceRecordCommand(
                            source_record_id="PER-APP-UNREG-0003",
                            source_record_version="1",
                            payload={
                                "application_number": "SYN-APP-UNREG-03",
                                "permit_type": "com_ti",
                            },
                        )
                    ],
                ),
                steward(session),
            )
            assert result.registered is False
            assert result.staged == 1
            assert result.accepted == 0
            assert result.issue_ids

            snapshots = session.execute(
                select(source.SourceSnapshot).where(
                    source.SourceSnapshot.source_record_id == "PER-APP-UNREG-0003"
                )
            ).scalars().all()
            assert [row.record_status for row in snapshots] == ["staged"]

            issues = session.execute(
                select(change.GovernanceIssue).where(
                    change.GovernanceIssue.issue_type == "unregistered_dataset"
                )
            ).scalars().all()
            assert len(issues) == 1
            assert issues[0].blocking is True
            assert issues[0].assigned_actor_id == "service_governance_lead"
    finally:
        factory.dispose()


def test_an_invalid_record_is_quarantined_with_field_errors(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = IngestionService(session)
            result = service.ingest(
                command(
                    "permitting",
                    "applications_and_permits",
                    [
                        SourceRecordCommand(
                            source_record_id="PER-APP-BAD-0001",
                            source_record_version="1",
                            payload={
                                "application_number": "SYN-APP-BAD-01",
                                "permit_type": "not_a_permit_type",
                            },
                        )
                    ],
                ),
                steward(session),
            )
            assert result.quarantined == 1
            assert result.accepted == 0
            codes = {error.error_code for error in result.field_errors}
            assert "unsupported_value" in codes
            assert {error.field_path for error in result.field_errors} == {"permit_type"}

            errors = session.execute(
                select(source.QuarantineError)
            ).scalars().all()
            assert any(error.error_code == "unsupported_value" for error in errors)
            snapshot = session.execute(
                select(source.SourceSnapshot).where(
                    source.SourceSnapshot.source_record_id == "PER-APP-BAD-0001"
                )
            ).scalar_one()
            assert snapshot.record_status == "quarantined"
            assert snapshot.raw_payload["application_number"] == "SYN-APP-BAD-01"
    finally:
        factory.dispose()


def test_the_denominators_partition_the_received_count(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = IngestionService(session)
            result = service.ingest(
                command(
                    "permitting",
                    "applicant_profiles",
                    [
                        SourceRecordCommand(
                            source_record_id="PER-AP-9001",
                            source_record_version="1",
                            payload={**APPLICANT_PROFILE, "party_ref": "party_applicant_1"},
                        ),
                        SourceRecordCommand(
                            source_record_id="PER-AP-9002",
                            source_record_version="1",
                            payload={**APPLICANT_PROFILE, "party_ref": "party_applicant_2"},
                        ),
                    ],
                ),
                steward(session),
            )
            assert result.received == 2
            assert result.accepted == 2
            assert (
                result.accepted
                + result.unchanged
                + result.quarantined
                + result.unresolved
                + result.staged
                == result.received
            )

            observations = session.execute(
                select(source.SourceObservation).where(
                    source.SourceObservation.ingestion_run_id == result.ingestion_run_id
                )
            ).scalars().all()
            metrics = {row.metric: (row.numerator, row.denominator) for row in observations}
            assert metrics["records_received"] == (2, 2)
            assert metrics["records_accepted"] == (2, 2)
            assert all(denominator == 2 for _, denominator in metrics.values())
    finally:
        factory.dispose()


def test_the_receipt_time_never_replaces_the_source_times(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = IngestionService(session)
            service.ingest(
                command(
                    "permitting",
                    "applicant_profiles",
                    [
                        SourceRecordCommand(
                            source_record_id="PER-AP-9101",
                            source_record_version="1",
                            payload={**APPLICANT_PROFILE, "party_ref": "party_applicant_1"},
                            source_updated_at=datetime(2026, 9, 5, 13, 12, tzinfo=UTC),
                        )
                    ],
                    received_at=datetime(2026, 10, 20, 8, 0, tzinfo=UTC),
                ),
                steward(session),
            )
            snapshot = session.execute(
                select(source.SourceSnapshot).where(
                    source.SourceSnapshot.source_record_id == "PER-AP-9101"
                )
            ).scalar_one()
            assert snapshot.source_updated_at == datetime(2026, 9, 5, 13, 12, tzinfo=UTC)
            assert snapshot.ingested_at == datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
            assert snapshot.effective_from is None
    finally:
        factory.dispose()
