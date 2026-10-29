"""AT13: rule consistency and dates.

The same effective rule and fee versions and the same citations are used
throughout.  A resubmission preserves the initial submission date, an author
may not approve their own rule, and an overlapping published version is
refused without an explicit precedence.  The history is retained.

Every test here runs under both approval policies.  The consistent versions,
the preserved initial submission date, the overlap block and the retained
history hold in both.  The self-approval clause is the one that depends on the
policy: ``independent`` blocks it (that is the AT13 requirement), ``single``
allows it with a confirmation and a reason and records the basis.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError, ValidationError
from acme_city.core.results import ConflictResult
from acme_city.finance.schemas import AssessmentCommand
from acme_city.finance.service import FinanceService
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import finance
from acme_city.persistence.models.audit import AuditEvent
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.schemas import ReviseApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.rules.schemas import (
    DraftRuleCommand,
    PublishRuleCommand,
    RuleLifecycleCommand,
)
from acme_city.rules.service import RuleCatalogService

BASIS = datetime(2026, 9, 8, 14, 30, tzinfo=UTC)


@pytest.fixture(params=["independent", "single"], autouse=True)
def mode(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Run each AT13 test under both approval policies (ACME_APPROVAL_POLICY)."""
    monkeypatch.setenv("ACME_APPROVAL_POLICY", request.param)
    return request.param


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at13.db'}",
            "ACME_SECRET_KEY": "at13-rule-consistency-secret-value",
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


def test_the_evaluation_and_the_assessment_use_the_same_versions(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            administrator = context_for(session, "persona_city_administrator")

            evaluation = service.evaluate("app_synth_001", reviewer)
            assessment = FinanceService(session).assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )

            catalogue = RuleCatalogService(session)
            rule_set = catalogue.resolve("executable", "com_ti", BASIS)
            schedule = catalogue.resolve("fee_schedule", "com_ti", BASIS)

            assert evaluation.rule_versions == rule_set.version_labels()
            assert evaluation.citations == rule_set.citations
            assert assessment.fee_schedule_version == schedule.fee_schedule.version_label
            stored = session.execute(
                select(finance.Assessment).where(
                    finance.Assessment.id == assessment.assessment_id
                )
            ).scalar_one()
            assert stored.input_versions["fee_schedule_version"] == "2026.1"
            assert stored.input_versions["initial_submitted_at"] == BASIS.isoformat()
    finally:
        factory.dispose()


def test_a_resubmission_preserves_the_initial_submission_date(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            steward = context_for(session, "persona_data_steward")
            reviewer = context_for(session, "persona_permit_reviewer")

            before = service.application_view(service.load_application("app_synth_001"))
            assert before.initial_submitted_at == BASIS

            revised = service.revise(
                ReviseApplicationCommand(
                    application_id="app_synth_001",
                    facts={"valuation": 70000.0, "valuation_cents": 7000000},
                    reason="Fictional demonstration correction.",
                ),
                steward,
            )
            assert revised.initial_submitted_at == BASIS
            assert revised.revision_submitted_at != BASIS

            # The rules are still selected on the initial submission date.
            evaluation = service.evaluate("app_synth_001", reviewer)
            assert evaluation.rule_versions == {"CT-1": "CT-1@1", "CT-2": "CT-2@1"}
            assert evaluation.date_basis == f"initial_submitted_at@{BASIS.isoformat()}"
    finally:
        factory.dispose()


def test_an_author_may_not_approve_their_own_rule(seeded: Settings, mode: str) -> None:
    """AT13 self-approval clause: blocked when independent, recorded when single."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            catalogue = RuleCatalogService(session)
            # The City Administrator holds the approval grant, so in independent mode the
            # block below is the author check and not a missing permission.
            author = context_for(session, "persona_city_administrator")
            drafted = catalogue.draft(
                DraftRuleCommand(
                    rule_id="CT-3",
                    permit_type_key="com_ti",
                    title="Emergency access review",
                    citation="ACME Code §14-418",
                    field_path="occupancy_load",
                    operator="max",
                    limit_value="60",
                    on_violate="condition",
                    effective_from=BASIS,
                    reason="Fictional demonstration rule.",
                ),
                author,
            )
            reviewed = catalogue.submit_for_review(
                RuleLifecycleCommand(
                    rule_version_id=drafted.value.row_id,
                    expected_version=drafted.version,
                    reason="Ready for review.",
                ),
                author,
            )
            stored = session.execute(
                select(finance.RuleVersion).where(
                    finance.RuleVersion.id == drafted.value.row_id
                )
            ).scalar_one()
            if mode == "independent":
                with pytest.raises(PermissionDeniedError):
                    catalogue.approve(
                        RuleLifecycleCommand(
                            rule_version_id=drafted.value.row_id,
                            expected_version=reviewed.version,
                            reason="Self approval.",
                            confirm_author_approval=True,
                        ),
                        author,
                    )
                assert stored.status == "in_review"
                return
            # Single-administrator policy: the author needs a reason and a confirmation.
            with pytest.raises(ValidationError):
                catalogue.approve(
                    RuleLifecycleCommand(
                        rule_version_id=drafted.value.row_id,
                        expected_version=reviewed.version,
                        reason="",
                        confirm_author_approval=True,
                    ),
                    author,
                )
            with pytest.raises(ValidationError):
                catalogue.approve(
                    RuleLifecycleCommand(
                        rule_version_id=drafted.value.row_id,
                        expected_version=reviewed.version,
                        reason="Self approval.",
                    ),
                    author,
                )
            assert stored.status == "in_review"
            approved = catalogue.approve(
                RuleLifecycleCommand(
                    rule_version_id=drafted.value.row_id,
                    expected_version=reviewed.version,
                    reason="Self approval under the single-administrator policy.",
                    confirm_author_approval=True,
                ),
                author,
            )
            assert stored.status == "approved"
            event = session.execute(
                select(AuditEvent).where(AuditEvent.id == approved.audit_event_id)
            ).scalar_one()
            assert event.metadata_json["approval_basis_label"] == (
                "Approved by the author (single-administrator policy)"
            )
            assert event.reason == "Self approval under the single-administrator policy."
    finally:
        factory.dispose()


def test_an_overlapping_published_version_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            catalogue = RuleCatalogService(session)
            administrator = context_for(session, "persona_city_administrator")
            candidate = session.execute(
                select(finance.RuleVersion).where(
                    finance.RuleVersion.id == "rulever_CT-2_v2"
                )
            ).scalar_one()
            reviewed = catalogue.submit_for_review(
                RuleLifecycleCommand(
                    rule_version_id=candidate.id,
                    expected_version=candidate.version,
                    reason="Ready for review.",
                ),
                administrator,
            )
            approved = catalogue.approve(
                RuleLifecycleCommand(
                    rule_version_id=candidate.id,
                    expected_version=reviewed.version,
                    reason="Approved against the fictional catalogue.",
                ),
                administrator,
            )
            refused = catalogue.publish(
                PublishRuleCommand(
                    rule_version_id=candidate.id,
                    expected_version=approved.version,
                    reason="Publication attempt.",
                ),
                administrator,
            )
            assert isinstance(refused, ConflictResult)
            assert refused.code == "overlapping_published_version"

            # The history of both versions is retained.
            versions = session.execute(
                select(finance.RuleVersion).where(
                    finance.RuleVersion.rule_id == "CT-2"
                )
            ).scalars().all()
            assert len(versions) == 2
            assert {row.status for row in versions} == {"published", "approved"}
    finally:
        factory.dispose()


def test_the_catalogue_retains_one_citation_per_rule(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(finance.RuleVersion).where(
                    finance.RuleVersion.status == "published"
                )
            ).scalars().all()
            citations = {}
            for row in rows:
                citations.setdefault(row.citation, set()).add(row.rule_id)
            for citation, rule_ids in citations.items():
                assert len(rule_ids) == 1, f"{citation} is used by more than one rule"
            # Every published rule carries exactly one citation.
            assert all(row.citation for row in rows)
    finally:
        factory.dispose()
