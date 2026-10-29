"""Rule catalogue tests: the lifecycle, publication gates and retrieval.

The catalogue is the single source of truth for retrieval, execution and
citation.  These tests prove the lifecycle, the author/approver separation,
the refusal of an overlapping published version and the selection of exactly
one version for a basis date.
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
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import finance
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.rules.schemas import (
    DraftFeeScheduleCommand,
    DraftRuleCommand,
    FeeScheduleLifecycleCommand,
    PublishRuleCommand,
    RetireRuleCommand,
    RuleLifecycleCommand,
)
from acme_city.rules.service import RuleCatalogService

BASIS = datetime(2026, 9, 8, 14, 30, tzinfo=UTC)
LATER_BASIS = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'rule-catalog.db'}",
            "ACME_SECRET_KEY": "rule-catalog-test-secret-value",
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


def test_the_catalogue_keeps_all_five_permit_configurations(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RuleCatalogService(session)
            expected = {
                "res_building": {"RB-1", "RB-2", "RB-3"},
                "deck_fence": {"DF-1", "DF-2", "DF-3", "DF-4"},
                "com_ti": {"CT-1", "CT-2"},
                "sign": {"SG-1", "SG-2", "SG-3", "SG-4"},
                "row_encroachment": {"RW-1", "RW-2", "RW-3"},
            }
            for permit_type, rule_ids in expected.items():
                rule_set = service.resolve("executable", permit_type, BASIS)
                assert {rule.rule_id for rule in rule_set.rules} == rule_ids
                assert rule_set.citations
                assert all(rule.status == "published" for rule in rule_set.rules)
    finally:
        factory.dispose()


def test_one_version_is_selected_for_a_basis_date(seeded: Settings) -> None:
    """The same rule never appears twice, whatever the basis date."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RuleCatalogService(session)
            for basis in (BASIS, LATER_BASIS):
                rule_set = service.resolve("executable", "com_ti", basis)
                labels = rule_set.version_labels()
                assert labels == {"CT-1": "CT-1@1", "CT-2": "CT-2@1"}
                assert rule_set.rule_set_id.endswith(basis.isoformat())
    finally:
        factory.dispose()


def test_the_published_fee_schedule_is_selected_by_its_effective_date(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RuleCatalogService(session)
            september = service.resolve("fee_schedule", "com_ti", BASIS)
            assert september.fee_schedule is not None
            assert september.fee_schedule.version_label == "2026.1"
            # The later schedule exists but is still a draft, so it is not in force.
            assert september.fee_schedule.definition["valuation_multiplier"] == "0.001"
    finally:
        factory.dispose()


def test_a_rule_moves_through_the_governed_lifecycle(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RuleCatalogService(session)
            steward = context_for(session, "persona_data_steward")
            administrator = context_for(session, "persona_city_administrator")

            drafted = service.draft(
                DraftRuleCommand(
                    rule_id="CT-3",
                    permit_type_key="com_ti",
                    title="Emergency access review",
                    citation="ACME Code §14-418",
                    field_path="occupancy_load",
                    operator="max",
                    limit_value="60",
                    on_violate="condition",
                    condition=None,
                    message="Occupancy load is above 60.",
                    condition_note="Emergency access sign-off required.",
                    effective_from=BASIS,
                    reason="Fictional demonstration rule.",
                ),
                steward,
            )
            assert drafted.value.status == "draft"
            rule_version_id = drafted.value.row_id

            reviewed = service.submit_for_review(
                RuleLifecycleCommand(
                    rule_version_id=rule_version_id,
                    expected_version=drafted.version,
                    reason="Ready for review.",
                ),
                steward,
            )
            assert reviewed.value.status == "in_review"

            approved = service.approve(
                RuleLifecycleCommand(
                    rule_version_id=rule_version_id,
                    expected_version=reviewed.version,
                    reason="Reviewed against the fictional catalogue.",
                ),
                administrator,
            )
            assert approved.value.status == "approved"
            assert approved.value.approver_actor_id == "persona_city_administrator"

            published = service.publish(
                PublishRuleCommand(
                    rule_version_id=rule_version_id,
                    expected_version=approved.version,
                    reason="Published for the demonstration.",
                ),
                administrator,
            )
            assert published.value.status == "published"
            assert published.value.citation == "ACME Code §14-418"

            rule_set = service.resolve("executable", "com_ti", BASIS)
            assert "CT-3" in rule_set.version_labels()

            retired = service.retire(
                RetireRuleCommand(
                    rule_version_id=rule_version_id,
                    expected_version=published.version,
                    effective_to=BASIS,
                    reason="Withdrawn from the fictional catalogue.",
                ),
                administrator,
            )
            assert retired.value.status == "retired"
            rule_set = service.resolve("executable", "com_ti", BASIS)
            assert "CT-3" not in rule_set.version_labels()
    finally:
        factory.dispose()


@pytest.mark.parametrize("mode", ["independent", "single"])
def test_an_author_may_not_approve_or_publish_their_own_rule(
    seeded: Settings, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """Blocked when independent. Under single, the author's missing approval grant still blocks it."""
    monkeypatch.setenv("ACME_APPROVAL_POLICY", mode)
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RuleCatalogService(session)
            steward = context_for(session, "persona_data_steward")
            drafted = service.draft(
                DraftRuleCommand(
                    rule_id="CT-4",
                    permit_type_key="com_ti",
                    title="Self approval attempt",
                    citation="ACME Code §14-419",
                    field_path="valuation",
                    operator="max",
                    limit_value="300000",
                    on_violate="review",
                    effective_from=BASIS,
                    reason="Fictional demonstration rule.",
                ),
                steward,
            )
            reviewed = service.submit_for_review(
                RuleLifecycleCommand(
                    rule_version_id=drafted.value.row_id,
                    expected_version=drafted.version,
                    reason="Ready for review.",
                ),
                steward,
            )
            # Under single the author also needs a reason and a confirmation first;
            # the Data Steward holds no approval grant, so the grant check still refuses.
            confirm = mode == "single"
            with pytest.raises(PermissionDeniedError):
                service.approve(
                    RuleLifecycleCommand(
                        rule_version_id=drafted.value.row_id,
                        expected_version=reviewed.version,
                        reason="Self approval.",
                        confirm_author_approval=confirm,
                    ),
                    steward,
                )
            stored = session.execute(
                select(finance.RuleVersion).where(
                    finance.RuleVersion.id == drafted.value.row_id
                )
            ).scalar_one()
            assert stored.status == "in_review"
    finally:
        factory.dispose()


def test_an_overlapping_published_version_is_refused(seeded: Settings) -> None:
    """A second published version of one rule needs an explicit precedence."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RuleCatalogService(session)
            administrator = context_for(session, "persona_city_administrator")
            candidate = session.execute(
                select(finance.RuleVersion).where(finance.RuleVersion.id == "rulever_CT-2_v2")
            ).scalar_one()
            assert candidate.status == "draft"

            reviewed = service.submit_for_review(
                RuleLifecycleCommand(
                    rule_version_id=candidate.id,
                    expected_version=candidate.version,
                    reason="Ready for review.",
                ),
                administrator,
            )
            approved = service.approve(
                RuleLifecycleCommand(
                    rule_version_id=candidate.id,
                    expected_version=reviewed.version,
                    reason="Approved against the fictional catalogue.",
                ),
                administrator,
            )
            refused = service.publish(
                PublishRuleCommand(
                    rule_version_id=candidate.id,
                    expected_version=approved.version,
                    reason="Publication attempt.",
                ),
                administrator,
            )
            assert isinstance(refused, ConflictResult)
            assert refused.code == "overlapping_published_version"
            assert refused.differences[0]["published_version_id"] == "rulever_CT-2_v1"

            stored = session.execute(
                select(finance.RuleVersion).where(finance.RuleVersion.id == candidate.id)
            ).scalar_one()
            assert stored.status == "approved"

            published = service.publish(
                PublishRuleCommand(
                    rule_version_id=candidate.id,
                    expected_version=approved.version,
                    reason="Published with an explicit precedence.",
                    precedence="supersedes:rulever_CT-2_v1",
                ),
                administrator,
            )
            assert published.value.status == "published"
            assert published.value.precedence == "supersedes:rulever_CT-2_v1"
    finally:
        factory.dispose()


def test_a_stale_expected_version_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RuleCatalogService(session)
            administrator = context_for(session, "persona_city_administrator")
            refused = service.approve(
                RuleLifecycleCommand(
                    rule_version_id="rulever_CT-2_v2",
                    expected_version=99,
                    reason="Stale expectation.",
                ),
                administrator,
            )
            assert isinstance(refused, ConflictResult)
            assert refused.code == "version_conflict"
            assert refused.current_version == 1
    finally:
        factory.dispose()


def test_a_citation_may_not_be_published_twice(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RuleCatalogService(session)
            steward = context_for(session, "persona_data_steward")
            administrator = context_for(session, "persona_city_administrator")
            drafted = service.draft(
                DraftRuleCommand(
                    rule_id="CT-5",
                    permit_type_key="com_ti",
                    title="Duplicate citation attempt",
                    citation="ACME Code §14-412",
                    field_path="occupancy_load",
                    operator="max",
                    limit_value="80",
                    on_violate="review",
                    effective_from=BASIS,
                    reason="Fictional demonstration rule.",
                ),
                steward,
            )
            reviewed = service.submit_for_review(
                RuleLifecycleCommand(
                    rule_version_id=drafted.value.row_id,
                    expected_version=drafted.version,
                    reason="Ready for review.",
                ),
                steward,
            )
            approved = service.approve(
                RuleLifecycleCommand(
                    rule_version_id=drafted.value.row_id,
                    expected_version=reviewed.version,
                    reason="Approved.",
                ),
                administrator,
            )
            refused = service.publish(
                PublishRuleCommand(
                    rule_version_id=drafted.value.row_id,
                    expected_version=approved.version,
                    reason="Publication attempt.",
                ),
                administrator,
            )
            assert isinstance(refused, ConflictResult)
            assert refused.code == "duplicate_citation"
    finally:
        factory.dispose()


def test_an_unsupported_operator_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RuleCatalogService(session)
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError):
                service.draft(
                    DraftRuleCommand(
                        rule_id="CT-6",
                        permit_type_key="com_ti",
                        title="Unsupported operator",
                        citation="ACME Code §14-420",
                        field_path="valuation",
                        operator="between",
                        limit_value="1",
                        effective_from=BASIS,
                        reason="Fictional demonstration rule.",
                    ),
                    steward,
                )
    finally:
        factory.dispose()


def test_a_fee_schedule_moves_through_the_governed_lifecycle(
    seeded: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fee schedule is governed exactly like a rule version."""
    # Pinned: the steward self-approval step below is about the independent policy
    # (approval policy setting, Randall).
    monkeypatch.setenv("ACME_APPROVAL_POLICY", "independent")
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RuleCatalogService(session)
            steward = context_for(session, "persona_data_steward")
            administrator = context_for(session, "persona_city_administrator")

            drafted = service.draft_fee_schedule(
                DraftFeeScheduleCommand(
                    fee_schedule_id="fee_commercial_demo",
                    version_label="2026.3",
                    effective_from=datetime(2027, 1, 1, tzinfo=UTC),
                    currency="USD",
                    definition={
                        "fixed_review_charge_cents": 12000,
                        "valuation_multiplier": "0.001",
                        "version_basis": "initial_submitted_at",
                    },
                    reason="Fictional demonstration schedule.",
                ),
                steward,
            )
            assert drafted.value.status == "draft"

            reviewed = service.submit_fee_schedule_for_review(
                FeeScheduleLifecycleCommand(
                    fee_schedule_version_id=drafted.value.row_id,
                    expected_version=drafted.version,
                    reason="Ready for review.",
                ),
                steward,
            )
            assert reviewed.value.status == "in_review"

            with pytest.raises(PermissionDeniedError):
                service.approve_fee_schedule(
                    FeeScheduleLifecycleCommand(
                        fee_schedule_version_id=drafted.value.row_id,
                        expected_version=reviewed.version,
                        reason="Self approval.",
                    ),
                    steward,
                )

            approved = service.approve_fee_schedule(
                FeeScheduleLifecycleCommand(
                    fee_schedule_version_id=drafted.value.row_id,
                    expected_version=reviewed.version,
                    reason="Approved against the fictional catalogue.",
                ),
                administrator,
            )
            assert approved.value.status == "approved"

            # The published schedule has to be retired first, so that the
            # two versions are never in force at the same time.
            current = session.execute(
                select(finance.FeeScheduleVersion).where(
                    finance.FeeScheduleVersion.id == "feesched_fee_commercial_demo_2026_1"
                )
            ).scalar_one()
            retired = service.retire_fee_schedule(
                FeeScheduleLifecycleCommand(
                    fee_schedule_version_id=current.id,
                    expected_version=current.version,
                    reason="Superseded by the next version of the schedule.",
                    effective_to=datetime(2027, 1, 1, tzinfo=UTC),
                ),
                administrator,
            )
            assert retired.value.status == "retired"

            published = service.publish_fee_schedule(
                FeeScheduleLifecycleCommand(
                    fee_schedule_version_id=drafted.value.row_id,
                    expected_version=approved.version,
                    reason="Published for the demonstration.",
                ),
                administrator,
            )
            assert published.value.status == "published"
            assert published.value.version_label == "2026.3"

            # The published schedule is in force from its effective date only.
            rule_set = service.resolve(
                "fee_schedule", "com_ti", datetime(2027, 2, 1, tzinfo=UTC)
            )
            assert rule_set.fee_schedule is not None
            assert rule_set.fee_schedule.version_label == "2026.3"
            # The retired schedule is no longer in force.
            rule_set = service.resolve("fee_schedule", "com_ti", BASIS)
            assert rule_set.fee_schedule is None
    finally:
        factory.dispose()


def test_an_overlapping_published_fee_schedule_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RuleCatalogService(session)
            administrator = context_for(session, "persona_city_administrator")
            candidate = session.execute(
                select(finance.FeeScheduleVersion).where(
                    finance.FeeScheduleVersion.id == "feesched_fee_commercial_demo_2026_2"
                )
            ).scalar_one()
            assert candidate.status == "draft"

            reviewed = service.submit_fee_schedule_for_review(
                FeeScheduleLifecycleCommand(
                    fee_schedule_version_id=candidate.id,
                    expected_version=candidate.version,
                    reason="Ready for review.",
                ),
                administrator,
            )
            approved = service.approve_fee_schedule(
                FeeScheduleLifecycleCommand(
                    fee_schedule_version_id=candidate.id,
                    expected_version=reviewed.version,
                    reason="Approved against the fictional catalogue.",
                ),
                administrator,
            )
            refused = service.publish_fee_schedule(
                FeeScheduleLifecycleCommand(
                    fee_schedule_version_id=candidate.id,
                    expected_version=approved.version,
                    reason="Publication attempt.",
                ),
                administrator,
            )
            assert isinstance(refused, ConflictResult)
            assert refused.code == "overlapping_published_version"

            published = service.publish_fee_schedule(
                FeeScheduleLifecycleCommand(
                    fee_schedule_version_id=candidate.id,
                    expected_version=approved.version,
                    reason="Published with an explicit precedence.",
                    precedence="supersedes:feesched_fee_commercial_demo_2026_1",
                ),
                administrator,
            )
            assert published.value.status == "published"
    finally:
        factory.dispose()


def test_an_applicant_may_not_change_the_catalogue(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RuleCatalogService(session)
            applicant = context_for(session, "persona_applicant")
            with pytest.raises(PermissionDeniedError):
                service.draft(
                    DraftRuleCommand(
                        rule_id="CT-7",
                        permit_type_key="com_ti",
                        title="Applicant attempt",
                        citation="ACME Code §14-421",
                        field_path="valuation",
                        operator="max",
                        limit_value="1",
                        effective_from=BASIS,
                        reason="Fictional demonstration rule.",
                    ),
                    applicant,
                )
    finally:
        factory.dispose()
