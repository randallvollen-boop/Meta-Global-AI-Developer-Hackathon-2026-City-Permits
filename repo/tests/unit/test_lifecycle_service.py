"""Lifecycle, reason codes, findings, comments, priority and assignment.

The lifecycle service owns the transitions a person makes on a case: return
it, advance it, ask the applicant for revisions, archive it and restore it.
Every transition checks the grant, the archived guard and a mandatory
expected version, and it records the reason code it used.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.agents.findings import current_findings, primary_finding
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError, ValidationError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.lifecycle import LifecycleService
from acme_city.permits.service import PermitService
from acme_city.permits.schemas import SubmitApplicationCommand

FACTS = {
    "valuation": "50000.00",
    "valuation_cents": 5000000,
    "project_description": "A fictional fence at 400 Lantern Row",
    "contractor_license": "ACME-LIC-1042",
    "submitted_parcel": "ACME-P-1001",
    "submitted_site_text": "400 Lantern Row, ACME City",
}


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'lifecycle.db'}",
            "ACME_SECRET_KEY": "lifecycle-test-secret-value",
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


def make_case(session, *, status: str = "needs_information") -> permit.Application:
    """Submit one fictional case and put it in the status the test needs."""
    service = PermitService(session)
    steward = context_for(session, "persona_data_steward")
    view = service.submit(
        SubmitApplicationCommand(
            permit_type_key="com_ti",
            facts=dict(FACTS),
            applicant_party_id="party_cedarline",
        ),
        steward,
    )
    application = service.load_application(view.application_id)
    application.status = status
    session.flush()
    return application


_FINDING_COUNTER = {"count": 0}


def make_finding(
    session,
    application: permit.Application,
    *,
    finding_type: str = "judgment",
    severity: str = "review",
    message: str = "A person must confirm the duplicate.",
) -> permit.ApplicationFinding:
    """Record one finding on a case."""
    _FINDING_COUNTER["count"] += 1
    row = permit.ApplicationFinding(
        id=f"finding_lifecycle_{_FINDING_COUNTER['count']}",
        correlation_id="corr_lifecycle",
        application_id=application.id,
        finding_type=finding_type,
        message=message,
        rule="ACME Code §13-401",
        applicant_must="Confirm the duplicate.",
        severity=severity,
        state="current",
        revision_number=application.revision,
        version=1,
    )
    session.add(row)
    session.flush()
    return row


# ------------------------------------------------------------------ statuses


def test_a_steward_returns_a_case_to_the_applicant(seeded: Settings) -> None:
    """A return needs a typed reason code and ends the case."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            version = application.version
            steward = context_for(session, "persona_data_steward")
            LifecycleService(session).return_application(
                application_id=application.id,
                reason_code="INCOMPLETE_APPLICATION",
                reason="The site plan is still missing.",
                actor=steward,
                expected_version=version,
            )
            session.refresh(application)
            assert application.status == "returned"
            assert application.version == version + 1
            actions = session.execute(
                select(permit.ApplicationAction).where(
                    permit.ApplicationAction.application_id == application.id
                )
            ).scalars().all()
            assert len(actions) == 1
            # The action record snapshots the code, its label and its version.
            assert actions[0].reason_code == "INCOMPLETE_APPLICATION"
            assert actions[0].reason_code_label == "Incomplete application"
            assert actions[0].reason_code_version == 1
            assert actions[0].action == "return"
    finally:
        factory.dispose()


def test_a_returned_case_is_terminal(seeded: Settings) -> None:
    """A returned case is not reopened by a revision, an evaluation or an agent."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            steward = context_for(session, "persona_data_steward")
            LifecycleService(session).return_application(
                application_id=application.id,
                reason_code="INCOMPLETE_APPLICATION",
                actor=steward,
                expected_version=application.version,
            )
            session.refresh(application)
            from acme_city.permits.schemas import ReviseApplicationCommand

            with pytest.raises(ValidationError):
                PermitService(session).revise(
                    ReviseApplicationCommand(
                        application_id=application.id,
                        facts={"valuation": "60000.00"},
                        reason="A fictional correction.",
                    ),
                    steward,
                )
            reviewer = context_for(session, "persona_permit_reviewer")
            with pytest.raises(ValidationError):
                PermitService(session).evaluate(application.id, reviewer)
    finally:
        factory.dispose()


def test_a_return_with_a_code_of_another_type_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError):
                LifecycleService(session).return_application(
                    application_id=application.id,
                    reason_code="DOES_NOT_MEET_CODE",
                    actor=steward,
                    expected_version=application.version,
                )
    finally:
        factory.dispose()


def test_a_return_without_the_grant_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            reviewer = context_for(session, "persona_permit_reviewer")
            with pytest.raises(PermissionDeniedError):
                LifecycleService(session).return_application(
                    application_id=application.id,
                    reason_code="INCOMPLETE_APPLICATION",
                    actor=reviewer,
                    expected_version=application.version,
                )
    finally:
        factory.dispose()


def test_a_return_needs_an_expected_version(seeded: Settings) -> None:
    """A missing expected version is refused as well as a stale one."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError):
                LifecycleService(session).return_application(
                    application_id=application.id,
                    reason_code="INCOMPLETE_APPLICATION",
                    actor=steward,
                    expected_version=None,
                )
            with pytest.raises(ValidationError):
                LifecycleService(session).return_application(
                    application_id=application.id,
                    reason_code="INCOMPLETE_APPLICATION",
                    actor=steward,
                    expected_version=application.version + 99,
                )
    finally:
        factory.dispose()


def test_advancing_to_review_is_refused_while_a_blocking_finding_stands(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            make_finding(
                session,
                application,
                finding_type="missing_document",
                severity="block",
                message="The site plan is missing.",
            )
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError):
                LifecycleService(session).advance_to_review(
                    application_id=application.id,
                    actor=steward,
                    expected_version=application.version,
                )
    finally:
        factory.dispose()


def test_advancing_to_review_succeeds_once_the_blocking_finding_is_waived(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            finding = make_finding(
                session,
                application,
                finding_type="duplicate",
                severity="block",
                message="The case repeats another one.",
            )
            steward = context_for(session, "persona_data_steward")
            lifecycle = LifecycleService(session)
            from acme_city.permits.finding_actions import waive_finding

            waive_finding(
                session,
                finding_id=finding.id,
                reason_code="WAIVE_VERIFIED_DUPLICATE",
                reason="A person confirmed the duplicate.",
                actor=steward,
                expected_version=application.version,
            )
            session.refresh(application)
            lifecycle.advance_to_review(
                application_id=application.id,
                actor=steward,
                expected_version=application.version,
            )
            session.refresh(application)
            assert application.status == "ready_for_review"
    finally:
        factory.dispose()


def test_a_reviewer_asks_the_applicant_for_revisions(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="under_review")
            reviewer = context_for(session, "persona_permit_reviewer")
            LifecycleService(session).request_revisions(
                application_id=application.id,
                reason_code="REVISION_NEEDS_PLANS",
                message="The plans must show the setback.",
                actor=reviewer,
                expected_version=application.version,
            )
            session.refresh(application)
            assert application.status == "revisions_requested"
            comments = session.execute(
                select(permit.ApplicationComment).where(
                    permit.ApplicationComment.application_id == application.id
                )
            ).scalars().all()
            assert len(comments) == 1
            assert comments[0].visibility == "applicant"
            assert comments[0].body == "The plans must show the setback."
    finally:
        factory.dispose()


def test_asking_for_revisions_needs_a_message_and_a_revision_code(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="under_review")
            reviewer = context_for(session, "persona_permit_reviewer")
            with pytest.raises(ValidationError):
                LifecycleService(session).request_revisions(
                    application_id=application.id,
                    reason_code="REVISION_NEEDS_PLANS",
                    message="",
                    actor=reviewer,
                    expected_version=application.version,
                )
            with pytest.raises(ValidationError):
                LifecycleService(session).request_revisions(
                    application_id=application.id,
                    reason_code="INCOMPLETE_APPLICATION",
                    message="A message.",
                    actor=reviewer,
                    expected_version=application.version,
                )
    finally:
        factory.dispose()


# ------------------------------------------------------------- archive/restore


def test_an_administrator_archives_and_restores_a_case(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="ready_for_review")
            administrator = context_for(session, "persona_city_administrator")
            lifecycle = LifecycleService(session)
            lifecycle.archive(
                application_id=application.id,
                reason_code="ARCHIVE_DUPLICATE_RECORD",
                reason="The case repeats another record.",
                actor=administrator,
                expected_version=application.version,
            )
            session.refresh(application)
            assert application.status == "archived"
            assert application.status_before_archive == "ready_for_review"
            assert application.archive_reason_code_id
            lifecycle.restore(
                application_id=application.id,
                actor=administrator,
                expected_version=application.version,
            )
            session.refresh(application)
            assert application.status == "ready_for_review"
    finally:
        factory.dispose()


def test_an_issued_case_is_never_archived(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="issued")
            administrator = context_for(session, "persona_city_administrator")
            with pytest.raises(ValidationError):
                LifecycleService(session).archive(
                    application_id=application.id,
                    reason_code="ARCHIVE_DUPLICATE_RECORD",
                    actor=administrator,
                    expected_version=application.version,
                )
    finally:
        factory.dispose()


def test_a_restore_does_not_revive_a_stale_approval(seeded: Settings) -> None:
    """A restore returns the case; a stale decision stays stale."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="approved")
            decision = permit.Decision(
                id="decision_stale_1",
                application_id=application.id,
                decision_type="review",
                outcome="approved",
                decided_by_actor_id="persona_permit_reviewer",
                decided_at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
                status="current",
                stale=True,
                version=1,
            )
            session.add(decision)
            session.flush()
            administrator = context_for(session, "persona_city_administrator")
            LifecycleService(session).archive(
                application_id=application.id,
                reason_code="ARCHIVE_DUPLICATE_RECORD",
                actor=administrator,
                expected_version=application.version,
            )
            session.refresh(application)
            LifecycleService(session).restore(
                application_id=application.id,
                actor=administrator,
                expected_version=application.version,
            )
            session.refresh(application)
            assert application.status == "approved"
            session.refresh(decision)
            assert decision.stale is True
    finally:
        factory.dispose()


# -------------------------------------------------------------------- findings


def test_the_primary_finding_groups_by_severity_and_the_stable_order(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            review = make_finding(
                session,
                application,
                finding_type="judgment",
                severity="review",
                message="A judgement.",
            )
            session.flush()
            conflict = make_finding(
                session,
                application,
                finding_type="conflict",
                severity="review",
                message="A conflict.",
            )
            session.flush()
            blocking = make_finding(
                session,
                application,
                finding_type="missing_document",
                severity="block",
                message="A missing document.",
            )
            session.flush()
            rows = current_findings(session, application.id)
            assert primary_finding(rows).id == blocking.id
            blocking.state = "resolved"
            session.flush()
            assert primary_finding(current_findings(session, application.id)).id == conflict.id
            assert review.id in {row.id for row in rows}
    finally:
        factory.dispose()
