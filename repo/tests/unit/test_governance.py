"""Governance tests: registration gate, assignments, escalation and authority."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.core.errors import (
    ConflictError,
    IncompleteRegistrationError,
    PermissionDeniedError,
)
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.governance.schemas import (
    DeactivateStewardCommand,
    EscalateIssueCommand,
    PreviewAuthorityChangeCommand,
    PublishAuthorityChangeCommand,
    RegisterDatasetCommand,
    ReassignStewardCommand,
)
from acme_city.governance.service import GovernanceService
from acme_city.persistence.models import audit, change, governance
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'governance.db'}",
            "ACME_SECRET_KEY": "governance-test-secret-value",
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


def actor(session, actor_id: str) -> ActorContext:
    from acme_city.auth.permissions import PermissionResolver

    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(governance.ActorRole.role_id).where(
                governance.ActorRole.actor_id == actor_id
            )
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


def test_incomplete_registration_cannot_publish(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = GovernanceService(session)
            lead = actor(session, "persona_city_administrator")
            result = service.register_dataset(
                RegisterDatasetCommand(
                    source_system_id="permitting",
                    dataset_key="unregistered_feeds",
                    label="An unregistered feed",
                    domain_id=None,
                    accountable_owner_actor_id=None,
                    steward_queue_id=None,
                    system_custodian_actor_id=None,
                    authority_policy_id=None,
                    correction_route=None,
                    schema_version="1.0",
                    business_key_fields=["application_number"],
                ),
                lead,
            )
            assert result.value.registration_state == "incomplete"
            assert result.value.publishable is False
            assert "accountable_owner" in result.value.missing_bindings

            with pytest.raises(IncompleteRegistrationError):
                service.publish_dataset("unregistered_feeds", lead)
    finally:
        factory.dispose()


def test_complete_registration_may_publish(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = GovernanceService(session)
            lead = actor(session, "persona_city_administrator")
            result = service.register_dataset(
                RegisterDatasetCommand(
                    source_system_id="permitting",
                    dataset_key="unregistered_feeds",
                    label="An unregistered feed",
                    domain_id="permits",
                    accountable_owner_actor_id="service_owner_building_safety",
                    steward_queue_id="queue_permits",
                    system_custodian_actor_id="service_custodian_permitting",
                    authority_policy_id="authority_application_facts",
                    correction_route="Permitting application workspace",
                    schema_version="1.0",
                    business_key_fields=["application_number"],
                ),
                lead,
            )
            assert result.value.registration_state == "complete"
            assert result.value.publishable is True
            published = service.publish_dataset("unregistered_feeds", lead)
            assert published.value.registration_state == "complete"
    finally:
        factory.dispose()


def test_registration_writes_an_audit_event_in_the_same_transaction(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = GovernanceService(session)
            lead = actor(session, "persona_city_administrator")
            result = service.register_dataset(
                RegisterDatasetCommand(
                    source_system_id="permitting",
                    dataset_key="unregistered_feeds",
                    label="An unregistered feed",
                    domain_id="permits",
                    accountable_owner_actor_id="service_owner_building_safety",
                    steward_queue_id="queue_permits",
                    system_custodian_actor_id="service_custodian_permitting",
                    authority_policy_id="authority_application_facts",
                    correction_route="Permitting application workspace",
                    schema_version="1.0",
                    business_key_fields=["application_number"],
                ),
                lead,
            )
            session.flush()
            event = session.get(audit.AuditEvent, result.audit_event_id)
            assert event is not None
            assert event.action == "governance.dataset.register"
            assert event.actor_id == "persona_city_administrator"
            assert event.outcome == "accepted"
    finally:
        factory.dispose()


def test_reassignment_updates_current_responsibility_and_keeps_history(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = GovernanceService(session)
            lead = actor(session, "persona_city_administrator")
            before = service.current_assignments("applicants")
            steward_before = next(a for a in before if a.responsibility == "steward")
            assert steward_before.actor_id == "persona_data_steward"

            result = service.reassign_steward(
                ReassignStewardCommand(
                    domain_id="applicants",
                    responsibility="steward",
                    new_actor_id="service_delegate_steward",
                    reason="fictional demonstration reassignment",
                ),
                lead,
            )
            assert result.value.actor_id == "service_delegate_steward"
            assert result.value.superseded_by_assignment_id is None

            after = service.current_assignments("applicants")
            steward_after = next(a for a in after if a.responsibility == "steward")
            assert steward_after.actor_id == "service_delegate_steward"
            assert steward_after.assignment_id != steward_before.assignment_id

            history = session.execute(
                select(governance.Assignment).where(
                    governance.Assignment.id == steward_before.assignment_id
                )
            ).scalar_one()
            assert history.effective_to is not None
            assert history.actor_id == "persona_data_steward"
            assert history.version >= 2
    finally:
        factory.dispose()


def test_deactivating_a_steward_with_active_work_is_a_conflict(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                change.ChangeCase(
                    id="case_for_steward",
                    correlation_id="corr_case_for_steward",
                    target_type="source_record",
                    target_id="PER-AP-0003",
                    change_kind="factual",
                    title="Fictional open case",
                    requester_actor_id="persona_applicant",
                    assignee_actor_id="persona_data_steward",
                    status="in_review",
                )
            )
            session.flush()
            service = GovernanceService(session)
            lead = actor(session, "persona_city_administrator")
            with pytest.raises(ConflictError):
                service.deactivate_steward(
                    DeactivateStewardCommand(
                        actor_id="persona_data_steward",
                        reason="fictional demonstration deactivation",
                    ),
                    lead,
                )
            assert (
                session.get(governance.Actor, "persona_data_steward").active is True
            )
    finally:
        factory.dispose()


def test_deactivation_with_reassignment_succeeds_and_moves_the_work(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                change.ChangeCase(
                    id="case_for_reassignment",
                    correlation_id="corr_case_for_reassignment",
                    target_type="source_record",
                    target_id="PER-AP-0003",
                    change_kind="factual",
                    title="Fictional open case",
                    requester_actor_id="persona_applicant",
                    assignee_actor_id="persona_data_steward",
                    status="in_review",
                )
            )
            session.flush()
            service = GovernanceService(session)
            lead = actor(session, "persona_city_administrator")
            result = service.deactivate_steward(
                DeactivateStewardCommand(
                    actor_id="persona_data_steward",
                    reason="fictional demonstration deactivation",
                    reassign_domain_id="applicants",
                    reassign_to_actor_id="service_delegate_steward",
                ),
                lead,
            )
            assert result.value.active is False
            deactivated = session.get(governance.Actor, "persona_data_steward")
            assert deactivated.active is False
            assert deactivated.deactivated_at is not None
            steward_after = next(
                a
                for a in service.current_assignments("applicants")
                if a.responsibility == "steward"
            )
            assert steward_after.actor_id == "service_delegate_steward"
    finally:
        factory.dispose()


def test_authority_impact_preview_lists_datasets_and_cases(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = GovernanceService(session)
            owner = actor(session, "service_owner_building_safety")
            preview = service.preview_authority_change(
                PreviewAuthorityChangeCommand(
                    policy_id="authority_application_facts",
                    field_group="Submitted project description, valuation, applicant declaration snapshot",
                    domain_id="permits",
                    authoritative_source_system_id="permitting",
                    authoritative_dataset_key="application_revisions",
                    change_destination="Permitting application revision",
                    user_action="Permits > Application > Submit correction",
                    requires_source_ack=True,
                    decision_relevant=True,
                ),
                owner,
            )
            assert preview.policy_id == "authority_application_facts"
            assert "application_revisions" in preview.impacted_datasets
            assert "SYN-APP-001" in preview.impacted_applications
            assert preview.requires_owner_approval is True
            assert preview.approver_actor_id == "service_owner_building_safety"
    finally:
        factory.dispose()


def test_publishing_an_authority_policy_refuses_author_self_approval(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = GovernanceService(session)
            owner = actor(session, "service_owner_building_safety")
            policy = session.execute(
                select(governance.AuthorityPolicy).where(
                    governance.AuthorityPolicy.policy_id == "authority_application_facts"
                )
            ).scalar_one()
            with pytest.raises(PermissionDeniedError):
                service.publish_authority_change(
                    PublishAuthorityChangeCommand(
                        policy_id="authority_application_facts",
                        approver_actor_id="service_owner_building_safety",
                        expected_version=policy.version,
                        reason="fictional demonstration self approval",
                    ),
                    owner,
                )
    finally:
        factory.dispose()


def test_publishing_an_authority_policy_refuses_a_stale_version(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = GovernanceService(session)
            owner = actor(session, "service_owner_building_safety")
            with pytest.raises(ConflictError):
                service.publish_authority_change(
                    PublishAuthorityChangeCommand(
                        policy_id="authority_application_facts",
                        approver_actor_id="service_governance_lead",
                        expected_version=99,
                        reason="fictional demonstration stale version",
                    ),
                    owner,
                )
    finally:
        factory.dispose()


def test_publishing_an_authority_policy_records_the_approver(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = GovernanceService(session)
            owner = actor(session, "service_owner_building_safety")
            policy = session.execute(
                select(governance.AuthorityPolicy).where(
                    governance.AuthorityPolicy.policy_id == "authority_application_facts"
                )
            ).scalar_one()
            result = service.publish_authority_change(
                PublishAuthorityChangeCommand(
                    policy_id="authority_application_facts",
                    approver_actor_id="service_governance_lead",
                    expected_version=policy.version,
                    reason="fictional demonstration publication",
                ),
                owner,
            )
            assert result.value.status == "published"
            assert result.value.approver_actor_id == "service_governance_lead"
            session.flush()
            event = session.get(audit.AuditEvent, result.audit_event_id)
            assert event is not None
            assert event.action == "governance.authority_policy.publish"
    finally:
        factory.dispose()


def test_escalation_routes_a_dispute_to_the_accountable_owner(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = GovernanceService(session)
            steward = actor(session, "persona_data_steward")
            result = service.escalate_issue(
                EscalateIssueCommand(
                    domain_id="applicants",
                    subject_type="source_record",
                    subject_id="PER-AP-0003",
                    issue_type="disputed_authority",
                    description="Fictional disputed identity authority",
                ),
                steward,
            )
            assert result.value.assigned_actor_id == "service_owner_building_safety"
            assert result.value.blocking is True
            issues = session.execute(
                select(func.count()).select_from(change.GovernanceIssue)
            ).scalar_one()
            assert issues == 1
    finally:
        factory.dispose()


def test_audit_trail_has_no_update_or_delete_operation() -> None:
    assert not hasattr(audit.AuditEvent, "update")
    assert not hasattr(audit.AuditEvent, "delete")
    columns = set(audit.AuditEvent.__table__.columns.keys())
    assert "before_version" in columns
    assert "after_version" in columns
    assert "version" not in columns
