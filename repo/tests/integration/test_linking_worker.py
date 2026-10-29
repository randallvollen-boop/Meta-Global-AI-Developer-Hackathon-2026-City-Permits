"""Accepted source versions enqueue durable linking work exactly once."""

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
from acme_city.persistence.models import registry_automation, source
from acme_city.registry.automation import enqueue_accepted_snapshot
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

PAYLOAD = {
    "party_ref": "party_applicant_1",
    "display_name": "Tamsin Aldous",
    "contact_email": "t.aldous+autolink@example.invalid",
    "contact_phone": "+1-555-0141",
    "preferred_contact": "email",
}

@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'linking-worker.db'}",
            "ACME_SECRET_KEY": "linking-worker-test-secret",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(DemoEnvironment(
                id="demo_environment_local",
                environment_id=ENVIRONMENT_ID,
                fictional_demo=True,
                fixture_version=bundle.fixture_version,
                label="local fictional demonstration",
            ))
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    finally:
        factory.dispose()
    return settings


def test_accepted_version_enqueues_once_when_policy_is_active(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            session.add(registry_automation.RegistryAutomationPolicy(
                id="policy_active_1",
                version=1,
                mode="active",
                status="active",
                matcher_version="registry-candidates-v1",
                thresholds={},
                source_scopes=["applicant_profiles"],
                reason="exercise durable enqueue",
                recorded_by_actor_id="persona_data_steward",
                activated_at=datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
            ))
        intake = IngestCommand(
            source_system_id="permitting",
            dataset_key="applicant_profiles",
            records=[SourceRecordCommand(
                source_record_id="PER-AP-0001",
                source_record_version="4",
                payload=PAYLOAD,
                source_updated_at=datetime(2026, 10, 29, 12, 1, tzinfo=UTC),
            )],
        )
        actor = ActorContext(actor_id="persona_data_steward", role_ids=frozenset())
        with transaction(factory) as session:
            service = IngestionService(session, registry_automation_mode="active")
            first = service.ingest(intake, actor)
            assert first.accepted == 1
        with transaction(factory) as session:
            service = IngestionService(session, registry_automation_mode="active")
            repeated = service.ingest(intake, actor)
            assert repeated.unchanged == 1
            jobs = session.execute(
                select(registry_automation.RegistryAutomationJob)
            ).scalars().all()
            assert len(jobs) == 1
            assert jobs[0].target_family == "owner_party"
            assert jobs[0].status == "pending"
            assert jobs[0].policy_id == "policy_active_1"
            snapshot = session.get(source.SourceSnapshot, jobs[0].source_snapshot_id)
            assert snapshot is not None
            duplicate_one = enqueue_accepted_snapshot(
                session, snapshot, dataset_key="applicant_profiles", automation_mode="active"
            )
            duplicate_two = enqueue_accepted_snapshot(
                session, snapshot, dataset_key="applicant_profiles", automation_mode="active"
            )
            assert duplicate_one is not None
            assert duplicate_two is not None
            assert duplicate_one.id == duplicate_two.id == jobs[0].id
            persisted = session.execute(
                select(registry_automation.RegistryAutomationJob)
            ).scalars().all()
            assert len(persisted) == 1
    finally:
        factory.dispose()



@pytest.mark.parametrize(
    ("policy_mode", "source_scopes"),
    [
        ("paused", ["applicant_profiles"]),
        ("active", ["contractor_register"]),
    ],
)
def test_policy_mode_and_source_scope_gate_enqueue(
    seeded: Settings, policy_mode: str, source_scopes: list[str]
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            session.add(registry_automation.RegistryAutomationPolicy(
                id=f"policy_gate_{policy_mode}",
                version=1,
                mode=policy_mode,
                status="active",
                matcher_version="registry-candidates-v1",
                thresholds={},
                source_scopes=source_scopes,
                reason="exercise policy enqueue gates",
                recorded_by_actor_id="persona_data_steward",
                activated_at=datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
            ))
        intake = IngestCommand(
            source_system_id="permitting",
            dataset_key="applicant_profiles",
            records=[SourceRecordCommand(
                source_record_id="PER-AP-0001",
                source_record_version="4",
                payload=PAYLOAD,
                source_updated_at=datetime(2026, 10, 29, 12, 1, tzinfo=UTC),
            )],
        )
        actor = ActorContext(actor_id="persona_data_steward", role_ids=frozenset())
        with transaction(factory) as session:
            result = IngestionService(
                session, registry_automation_mode="active"
            ).ingest(intake, actor)
            assert result.accepted == 1
            assert session.execute(
                select(registry_automation.RegistryAutomationJob)
            ).scalars().all() == []
    finally:
        factory.dispose()
