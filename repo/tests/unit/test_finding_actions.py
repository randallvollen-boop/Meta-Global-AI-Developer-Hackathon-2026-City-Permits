"""The waiver a Data Steward records against a finding.

A waiver applies to a current finding of a waivable type.  It records the
reason code, the free-text reason, who waived it and when, and it never
clears a deterministic rule failure or an identity, credential, finance or
parcel-clearance check.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.agents.findings import WAIVABLE_TYPES, blocking_findings
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError, ValidationError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.decisions import PermitDecisionCommand
from acme_city.permits.finding_actions import waive_finding
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


def _current_version(session, application_id: str) -> int:
    """Return the application version a decision is made against."""
    from acme_city.permits.service import PermitService

    return PermitService(session).load_application(application_id).version


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'waivers.db'}",
            "ACME_SECRET_KEY": "waiver-test-secret-value",
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


def make_finding(
    session,
    application: permit.Application,
    *,
    finding_type: str = "judgment",
    severity: str = "review",
    message: str = "A person must confirm the duplicate.",
) -> permit.ApplicationFinding:
    """Record one finding on a case."""
    row = permit.ApplicationFinding(
        id="finding_waiver_1",
        correlation_id="corr_waiver",
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


def test_a_waiver_records_the_code_the_reason_the_actor_and_the_time(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            finding = make_finding(session, application)
            steward = context_for(session, "persona_data_steward")
            waive_finding(
                session,
                finding_id=finding.id,
                reason_code="WAIVE_MINOR_DOCUMENT_DEFECT",
                reason="The defect does not change the assessment.",
                actor=steward,
                expected_version=application.version,
            )
            session.refresh(finding)
            assert finding.waived_at is not None
            assert finding.waived_by_actor_id == "persona_data_steward"
            assert finding.waiver_reason_code == "WAIVE_MINOR_DOCUMENT_DEFECT"
            assert finding.waiver_reason_code_label == "Minor document defect"
            assert finding.waiver_reason_code_version == 1
            assert finding.waiver_reason == "The defect does not change the assessment."
    finally:
        factory.dispose()


def test_only_a_waivable_finding_of_a_steward_may_be_waived(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            finding = make_finding(
                session,
                application,
                finding_type="missing_document",
                severity="block",
                message="The site plan is missing.",
            )
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError):
                waive_finding(
                    session,
                    finding_id=finding.id,
                    reason_code="WAIVE_MINOR_DOCUMENT_DEFECT",
                    reason="A reason.",
                    actor=steward,
                    expected_version=application.version,
                )
            reviewer = context_for(session, "persona_permit_reviewer")
            with pytest.raises(PermissionDeniedError):
                waive_finding(
                    session,
                    finding_id=finding.id,
                    reason_code="WAIVE_MINOR_DOCUMENT_DEFECT",
                    reason="A reason.",
                    actor=reviewer,
                    expected_version=application.version,
                )
    finally:
        factory.dispose()


def test_a_waiver_needs_a_grant_a_version_and_a_reason(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            finding = make_finding(session, application)
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError):
                waive_finding(
                    session,
                    finding_id=finding.id,
                    reason_code="WAIVE_MINOR_DOCUMENT_DEFECT",
                    reason="A reason.",
                    actor=steward,
                    expected_version=None,
                )
            with pytest.raises(ValidationError):
                waive_finding(
                    session,
                    finding_id=finding.id,
                    reason_code="WAIVE_MINOR_DOCUMENT_DEFECT",
                    reason="A reason.",
                    actor=steward,
                    expected_version=application.version + 3,
                )
            with pytest.raises(ValidationError):
                waive_finding(
                    session,
                    finding_id=finding.id,
                    reason_code="WAIVE_MINOR_DOCUMENT_DEFECT",
                    reason="",
                    actor=steward,
                    expected_version=application.version,
                )
            with pytest.raises(ValidationError):
                waive_finding(
                    session,
                    finding_id=finding.id,
                    reason_code="INCOMPLETE_APPLICATION",
                    reason="A reason.",
                    actor=steward,
                    expected_version=application.version,
                )
    finally:
        factory.dispose()


def test_a_waiver_never_clears_a_deterministic_decision_blocker(
    seeded: Settings,
) -> None:
    """A waived finding does not unblock a decision refused for a rule."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="ready_for_review")
            finding = make_finding(session, application)
            steward = context_for(session, "persona_data_steward")
            waive_finding(
                session,
                finding_id=finding.id,
                reason_code="WAIVE_VERIFIED_DUPLICATE",
                reason="A person confirmed the duplicate.",
                actor=steward,
                expected_version=application.version,
            )
            # The decision blockers of the case are unchanged by the waiver.
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            service.evaluate(application.id, reviewer)
            evaluation = service.current_evaluation(application.id)
            assert evaluation is not None
            from acme_city.permits.decisions import PermitDecisionService

            blockers = PermitDecisionService(session).blockers(
                service.load_application(application.id), evaluation
            )
            assert any(row.code.startswith("rule_") for row in blockers)
    finally:
        factory.dispose()


def test_a_decision_snapshots_the_waivers_that_applied(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="ready_for_review")
            finding = make_finding(session, application)
            steward = context_for(session, "persona_data_steward")
            waive_finding(
                session,
                finding_id=finding.id,
                reason_code="WAIVE_VERIFIED_DUPLICATE",
                reason="A person confirmed the duplicate.",
                actor=steward,
                expected_version=application.version,
            )
            session.refresh(application)
            reviewer = context_for(session, "persona_permit_reviewer")
            service = PermitService(session)
            evaluation = service.evaluate(application.id, reviewer)
            result = service.decide(
                PermitDecisionCommand(
                    application_id=application.id,
                    expected_application_version=_current_version(session, application.id),
                    outcome="denied",
                    reason="A fictional denial.",
                    reason_code="DOES_NOT_MEET_CODE",
                    expected_evaluation_version=evaluation.version,
                ),
                reviewer,
            )
            assert result.value.waivers
            assert result.value.waivers[0]["finding_id"] == finding.id
            assert result.value.reason_code == "DOES_NOT_MEET_CODE"
    finally:
        factory.dispose()


def test_a_waived_finding_does_not_block_the_advance(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            finding = make_finding(
                session,
                application,
                finding_type="judgment",
                severity="block",
                message="A person must confirm.",
            )
            assert [row.id for row in blocking_findings(session, application.id)] == [
                finding.id
            ]
            steward = context_for(session, "persona_data_steward")
            waive_finding(
                session,
                finding_id=finding.id,
                reason_code="WAIVE_VERIFIED_DUPLICATE",
                reason="A person confirmed it.",
                actor=steward,
                expected_version=application.version,
            )
            assert blocking_findings(session, application.id) == []
    finally:
        factory.dispose()


def test_only_a_waivable_type_may_be_waived() -> None:
    assert "judgment" in WAIVABLE_TYPES
    assert "missing_field" not in WAIVABLE_TYPES
    assert "missing_document" not in WAIVABLE_TYPES
    assert "fee" not in WAIVABLE_TYPES
