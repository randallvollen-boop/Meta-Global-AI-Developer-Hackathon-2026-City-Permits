"""Schema tests: foreign keys, references, versioning, money and time columns."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, StatementError

from acme_city.core.clock import utc_now
from acme_city.core.config import Settings
from acme_city.persistence.base import Base
from acme_city.persistence.models import (  # noqa: F401  (registers every table)
    agent,
    audit,
    change,
    finance,
    governance,
    model_run,
    permit,
    registry,
    source,
)
from acme_city.persistence.session import (
    SessionFactory,
    database_health,
    initialize_database,
    transaction,
)

#: Every object group the specification requires, with the tables that carry it.
REQUIRED_OBJECT_GROUPS: dict[str, tuple[str, ...]] = {
    "governance": (
        "roles",
        "permissions",
        "role_permissions",
        "actors",
        "actor_roles",
        "actor_grants",
        "domains",
        "steward_queues",
        "assignments",
        "source_contracts",
        "authority_policies",
        "demo_environment",
        "sessions",
    ),
    "source": (
        "source_systems",
        "ingestion_runs",
        "source_snapshots",
        "quarantine_errors",
        "source_observations",
    ),
    "registry": (
        "canonical_entities",
        "parties",
        "party_aliases",
        "party_contacts",
        "parcels",
        "addresses",
        "parcel_addresses",
        "credentials",
        "finance_accounts",
        "crosswalks",
        "match_proposals",
        "provenance",
    ),
    "change": (
        "change_cases",
        "source_commands",
        "change_dependencies",
        "review_tasks",
        "outbox_deliveries",
        "consumer_acknowledgements",
        "governance_issues",
    ),
    "permit": (
        "permit_types",
        "permit_type_icons",
        "applications",
        "application_revisions",
        "application_parties",
        "application_sites",
        "documents",
        "extraction_observations",
        "evaluations",
        "application_actions",
        "application_comments",
        "recommendations",
        "decisions",
        "permits",
        "impact_reviews",
    ),
    "finance": (
        "rule_versions",
        "fee_schedule_versions",
        "assessments",
        "assessment_lines",
        "payments",
        "payment_events",
        "allocations",
        "reconciliation_results",
        "finance_account_links",
    ),
    "model_run": ("model_runs", "model_inputs", "model_outputs", "evidence_references"),
    "audit": ("audit_events", "audit_references"),
    "agent": ("agent_steps", "agent_controls", "agent_runs", "agent_run_nodes"),
    "configuration": ("reason_codes",),
    "finding": ("application_findings",),
    "property_master": (
        "gis_streets",
        "zoning_districts",
        "application_parcel_matches",
        "dataset_subscribers",
        "application_drafts",
        "draft_documents",
    ),
}


@pytest.fixture()
def database(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'schema.db'}",
            "ACME_SECRET_KEY": "schema-test-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    return settings


def test_metadata_covers_every_required_object_group() -> None:
    tables = set(Base.metadata.tables)
    for group, expected_tables in REQUIRED_OBJECT_GROUPS.items():
        missing = [name for name in expected_tables if name not in tables]
        assert not missing, f"{group} is missing tables: {missing}"
    unexpected = tables - {name for names in REQUIRED_OBJECT_GROUPS.values() for name in names}
    assert not unexpected, f"tables outside the required groups: {sorted(unexpected)}"


def test_foreign_keys_are_enforced(database: Settings) -> None:
    factory = SessionFactory(database.database_url)
    try:
        with factory() as session:
            assert session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    finally:
        factory.dispose()


def test_invalid_reference_is_rejected(database: Settings) -> None:
    factory = SessionFactory(database.database_url)
    try:
        with pytest.raises(IntegrityError):
            with transaction(factory) as session:
                session.add(
                    governance.ActorGrant(
                        id="grant_orphan",
                        actor_id="actor_missing",
                        permission_id="permits.application.decide",
                        record_scope=[],
                        effective_from=utc_now(),
                    )
                )
    finally:
        factory.dispose()


def test_invalid_reference_leaves_no_partial_write(database: Settings) -> None:
    factory = SessionFactory(database.database_url)
    try:
        with pytest.raises(IntegrityError):
            with transaction(factory) as session:
                session.add(
                    governance.Actor(
                        id="actor_ok",
                        actor_id="actor_ok",
                        label="Fictional actor",
                        active=True,
                        fictional=True,
                    )
                )
                session.add(
                    governance.ActorGrant(
                        id="grant_bad",
                        actor_id="actor_missing",
                        permission_id="permits.application.decide",
                        record_scope=[],
                        effective_from=utc_now(),
                    )
                )
        with factory() as session:
            assert session.get(governance.Actor, "actor_ok") is None
    finally:
        factory.dispose()


def test_mutable_aggregates_start_at_version_one(database: Settings) -> None:
    factory = SessionFactory(database.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                governance.Domain(
                    id="domain_test",
                    domain_id="applicants",
                    label="Applicant profiles and party relationships",
                    active=True,
                )
            )
        with factory() as session:
            domain = session.get(governance.Domain, "domain_test")
            assert domain is not None
            assert domain.version == 1
    finally:
        factory.dispose()


def test_money_is_stored_as_integer_cents_with_currency() -> None:
    for table_name in ("assessments", "assessment_lines", "payments", "allocations"):
        columns = Base.metadata.tables[table_name].columns
        money_columns = [name for name in columns.keys() if name.endswith("_cents")]
        assert money_columns, f"{table_name} has no cents column"
        for name in money_columns:
            assert columns[name].type.__class__.__name__ == "Integer"
        assert "currency" in columns
        assert columns["currency"].type.length == 3


def test_timestamps_are_timezone_aware_and_unknown_times_stay_null(database: Settings) -> None:
    factory = SessionFactory(database.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                source.SourceSystem(
                    id="srcsys_permitting",
                    source_system_id="permitting",
                    label="Permitting (simulated)",
                    simulated=True,
                    incoming=True,
                )
            )
            session.flush()
            session.add(
                source.SourceSnapshot(
                    source_snapshot_id="snap_test",
                    correlation_id="corr_test",
                    source_system_id="permitting",
                    source_dataset_id="applicant_profiles",
                    source_record_id="PER-1",
                    source_record_version="1",
                    source_updated_at=None,
                    effective_from=None,
                    ingested_at=utc_now(),
                    payload_hash="0" * 64,
                    raw_payload={"name": "Fictional"},
                    record_status="accepted",
                )
            )
        with factory() as session:
            snapshot = session.get(source.SourceSnapshot, "snap_test")
            assert snapshot is not None
            assert snapshot.source_updated_at is None
            assert snapshot.effective_from is None
            assert snapshot.ingested_at.tzinfo is not None
            assert snapshot.ingested_at.utcoffset().total_seconds() == 0
    finally:
        factory.dispose()


def test_naive_datetime_is_rejected(database: Settings) -> None:
    factory = SessionFactory(database.database_url)
    try:
        with pytest.raises(StatementError) as caught:
            with transaction(factory) as session:
                session.add(
                    source.SourceSnapshot(
                        source_snapshot_id="snap_naive",
                        correlation_id="corr_naive",
                        source_system_id="permitting",
                        source_dataset_id="applicant_profiles",
                        source_record_id="PER-2",
                        ingested_at=datetime(2026, 1, 1, 12, 0, 0),  # naive on purpose
                        payload_hash="1" * 64,
                        record_status="accepted",
                    )
                )
        assert isinstance(caught.value.orig, ValueError)
    finally:
        factory.dispose()


def test_audit_table_records_before_and_after_versions() -> None:
    columns = Base.metadata.tables["audit_events"].columns
    assert "before_version" in columns
    assert "after_version" in columns
    assert "occurred_at" in columns
    assert "correlation_id" in columns


def test_database_health_reports_state_without_a_path(database: Settings) -> None:
    health = database_health(database)
    assert health.reachable is True
    assert health.state == "current"
    # Head is 0008 since the P3insight migration (synthetic flags, business categories).
    assert health.revision == "0008"
    assert database.database_url not in str(health.to_dict())


def test_database_health_reports_uninitialized_for_a_missing_database(tmp_path: Path) -> None:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'absent.db'}",
            "ACME_SECRET_KEY": "schema-test-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    health = database_health(settings)
    assert health.reachable is True
    assert health.state == "uninitialized"


def test_inspector_reports_created_tables(database: Settings) -> None:
    factory = SessionFactory(database.database_url)
    try:
        with factory.engine.connect() as connection:
            names = set(inspect(connection).get_table_names())
    finally:
        factory.dispose()
    for table_names in REQUIRED_OBJECT_GROUPS.values():
        for name in table_names:
            assert name in names
