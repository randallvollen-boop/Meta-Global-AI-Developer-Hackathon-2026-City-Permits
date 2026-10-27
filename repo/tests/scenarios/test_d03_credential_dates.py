"""D03: an expired contractor credential holds the dependent action.

The contractor registration of the D03 case expired before the decision
date.  The evaluation records it, the approval is refused with it, the issue
is routed to the registration steward and the issuance stays held.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import ValidationError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.governance.schemas import EscalateIssueCommand
from acme_city.governance.service import GovernanceService
from acme_city.persistence.models import change, registry
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.decisions import PermitDecisionCommand
from acme_city.permits.issuance import IssuePermitCommand, PermitIssuanceService
from acme_city.permits.service import PermitService


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'd03.db'}",
            "ACME_SECRET_KEY": "d03-credential-dates-secret-value",
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


def context_for(session, actor_id: str) -> ActorContext:
    """Return the server-resolved context of a seeded persona."""
    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
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


def test_the_expired_registration_is_recorded_and_holds_the_action(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")

            credential = session.execute(
                select(registry.Credential).where(
                    registry.Credential.credential_id == "cred_contractor_halcyon"
                )
            ).scalar_one()
            assert credential.valid_to is not None
            assert credential.valid_to.date().isoformat() == "2026-05-31"

            evaluation = service.evaluate("app_d03", reviewer)
            blockers = {
                blocker.code: blocker.detail for blocker in evaluation.blockers
            }
            assert "credential_expired" in blockers
            assert "2026-05-31" in blockers["credential_expired"]

            with pytest.raises(ValidationError) as raised:
                service.decide(
                    PermitDecisionCommand(
                        application_id="app_d03",
                        outcome="approved",
                        reason="Approval attempt.",
                        expected_evaluation_version=evaluation.version,
                    ),
                    reviewer,
                )
            codes = {blocker["code"] for blocker in raised.value.details["blockers"]}
            assert "credential_expired" in codes
            assert service.current_decision("app_d03") is None
    finally:
        factory.dispose()


def test_the_issue_is_routed_to_the_registration_steward(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            governance = GovernanceService(session)
            issue = governance.escalate_issue(
                EscalateIssueCommand(
                    domain_id="contractors",
                    subject_type="application",
                    subject_id="app_d03",
                    issue_type="credential_expired",
                    description=(
                        "The contractor registration CR-2025-00977 expired on 2026-05-31 "
                        "and the dependent action is held."
                    ),
                    reason="Fictional demonstration routing.",
                ),
                steward,
            )
            stored = session.execute(
                select(change.GovernanceIssue).where(
                    change.GovernanceIssue.id == issue.value.issue_id
                )
            ).scalar_one()
            assert stored.blocking is True
            assert stored.status == "open"
            assert stored.responsible_queue_id == "queue_contractors"
            assert stored.assigned_actor_id == "service_owner_building_safety"
    finally:
        factory.dispose()


def test_the_issuance_stays_held(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate("app_d03", reviewer)
            with pytest.raises(ValidationError):
                service.decide(
                    PermitDecisionCommand(
                        application_id="app_d03",
                        outcome="approved",
                        reason="Approval attempt.",
                        expected_evaluation_version=evaluation.version,
                    ),
                    reviewer,
                )
            application = service.load_application("app_d03")
            issuance = PermitIssuanceService(session)
            with pytest.raises(ValidationError):
                issuance.issue(
                    IssuePermitCommand(
                        application_id="app_d03",
                        decision_id="decision_d07",
                        expected_application_version=application.version,
                        expected_decision_version=1,
                        command_key="issue:d03:held",
                    ),
                    reviewer,
                )
    finally:
        factory.dispose()
