"""Trusted view tests: declared authority, provenance and unresolved authority."""

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
from acme_city.persistence.models import change, registry
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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'trusted-view.db'}",
            "ACME_SECRET_KEY": "trusted-view-secret-value",
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


def approve_link(
    session,
    source_system_id: str,
    dataset_key: str,
    record_id: str,
    reason: str = "fictional demonstration approval",
) -> None:
    """Propose and approve one source link through the registry service."""
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
            reason=reason,
            evidence=[
                {
                    "field": "party_ref",
                    "value": record_id,
                    "note": "the steward compared the declared reference with the registry",
                }
            ],
        ),
        steward(),
    )


def test_the_view_uses_the_declared_authority_and_keeps_the_disagreement(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = IngestionService(session)
            service.ingest(
                IngestCommand(
                    source_system_id="permitting",
                    dataset_key="applications_and_permits",
                    records=[
                        SourceRecordCommand(
                            source_record_id="PER-APP-NEWER-0001",
                            source_record_version="2",
                            payload={
                                "application_number": "SYN-APP-NEWER-01",
                                "permit_type": "com_ti",
                                "organization_name": "Cedarline Coffee Roasters LLC",
                                "contact_email": "newer@example.invalid",
                                "project_description": "A newer application record.",
                                "valuation": 1000.0,
                                "valuation_cents": 100000,
                                "submitted_site_text": "400 Lantern Row Unit 2, ACME City",
                                "submitted_parcel": "ACME-P-1001",
                            },
                            source_updated_at=datetime(2026, 10, 20, 8, 0, tzinfo=UTC),
                        )
                    ],
                ),
                steward(),
            )
        with transaction(factory) as session:
            approve_link(session, "permitting", "applicant_profiles", "PER-AP-0003")
            approve_link(
                session, "permitting", "applications_and_permits", "PER-APP-NEWER-0001"
            )
            service = RegistryService(session)
            view = service.trusted_view("party_cedarline")
            assert view is not None
            fields = {field.attribute_path: field for field in view.fields}
            display = fields["display_name"]
            assert display.state == "authoritative"
            assert display.authority_policy_id == "authority_person_identity"
            assert display.source_dataset_key == "applicant_profiles"
            assert display.value == "Cedar Line Coffee Roasters"

            disagreements = {item.attribute_path: item for item in view.disagreements}
            assert "display_name" in disagreements
            assert disagreements["display_name"].value == "Cedarline Coffee Roasters LLC"
            assert disagreements["display_name"].state == "disagreement"

            provenance = session.execute(
                select(registry.Provenance).where(
                    registry.Provenance.entity_id == "party_cedarline",
                    registry.Provenance.attribute_path == "display_name",
                )
            ).scalars().all()
            assert len(provenance) == 1
            assert provenance[0].authority_policy_id == "authority_person_identity"
            assert provenance[0].source_snapshot_id == display.source_snapshot_id
    finally:
        factory.dispose()


def test_an_unresolved_authority_creates_an_assigned_issue_and_a_blocker(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            approve_link(
                session, "permitting", "applications_and_permits", "PER-APP-SYN-APP-001"
            )
            service = RegistryService(session)
            view = service.trusted_view("party_cedarline")
            assert view is not None
            fields = {field.attribute_path: field for field in view.fields}
            contact = fields["contact_email"]
            assert contact.state == "disputed"
            assert contact.authority_policy_id == "authority_applicant_contact"
            assert view.issues
            issue_id = view.issues[0]["issue_id"]
            assert view.issues[0]["blocking"] is True

            issue = session.get(change.GovernanceIssue, issue_id)
            assert issue is not None
            assert issue.status == "open"
            assert issue.assigned_actor_id == "persona_data_steward"
            assert issue.responsible_queue_id == "queue_applicants"

            task = session.execute(
                select(change.ReviewTask).where(
                    change.ReviewTask.deduplication_key
                    == "field_authority:party_cedarline:contact_email"
                )
            ).scalar_one()
            assert task.status == "open"
            assert task.assignee_actor_id == "persona_data_steward"
    finally:
        factory.dispose()


def test_the_view_reports_an_absent_value_without_inventing_one(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            approve_link(session, "permitting", "applicant_profiles", "PER-AP-0003")
            service = RegistryService(session)
            view = service.trusted_view("party_cedarline")
            assert view is not None
            fields = {field.attribute_path: field for field in view.fields}
            assert fields["contact_email"].state == "authoritative"
            assert fields["contact_email"].value == "hello@cedarline.example.invalid"
            assert fields["business_license_status"].state == "absent"
            assert fields["business_license_status"].value is None
    finally:
        factory.dispose()
