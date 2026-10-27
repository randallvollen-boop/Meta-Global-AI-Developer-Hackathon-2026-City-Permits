"""Decision tests: an actual reviewer action, and what it refuses.

A decision is recorded by an authorized reviewer with the actor, the time,
the reason and the versions it was made against.  A request that only
supplies a ruling is not a transition, and an unresolved blocker refuses an
approval.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError, ValidationError
from acme_city.core.results import ConflictResult
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import finance, permit, registry
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.decisions import PermitDecisionCommand
from acme_city.permits.service import PermitService

DECIDED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'decisions.db'}",
            "ACME_SECRET_KEY": "decisions-test-secret-value",
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


def approve_links(session, party_ids: tuple[str, ...] = ("party_cedarline", "party_ironvale")) -> None:
    """Record the canonical links a steward would have approved."""
    for party_id in party_ids:
        session.add(
            registry.Crosswalk(
                id=f"crosswalk_{party_id}",
                entity_id=party_id,
                entity_type="party",
                source_system_id="permitting",
                source_dataset_key="applicant_profiles",
                source_record_id=f"PER-{party_id}",
                link_status="approved",
                decision="Approved by the data steward.",
                decision_actor_id="persona_data_steward",
                decided_at=DECIDED_AT,
            )
        )
    session.add(
        finance.FinanceAccountLink(
            id="faclink_legacy",
            account_id="facct_cedarline_legacy",
            party_id="party_cedarline",
            link_status="approved",
            decided_by_actor_id="persona_data_steward",
            decided_at=DECIDED_AT,
        )
    )
    session.flush()


def test_a_decision_records_the_actor_the_time_the_reason_and_the_versions(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate("app_synth_001", reviewer)
            result = service.decide(
                PermitDecisionCommand(
                    application_id="app_synth_001",
                    outcome="approved",
                    reason="Fictional demonstration approval.",
                    expected_evaluation_version=evaluation.version,
                ),
                reviewer,
            )
            assert not isinstance(result, ConflictResult)
            decision = result.value
            assert decision.decided_by_actor_id == "persona_permit_reviewer"
            assert decision.decided_at is not None
            assert decision.reason == "Fictional demonstration approval."
            assert decision.evaluation_id == evaluation.evaluation_id
            assert decision.input_versions["dependency_versions"]
            assert decision.rule_versions == {"CT-1": "CT-1@1", "CT-2": "CT-2@1"}
            assert decision.status == "current"
            assert decision.stale is False

            application = service.load_application("app_synth_001")
            assert application.status == "approved"
    finally:
        factory.dispose()


def test_a_request_that_only_supplies_a_ruling_is_refused(seeded: Settings) -> None:
    """A client cannot turn a field into a decision."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            service.evaluate("app_synth_001", reviewer)
            with pytest.raises(PydanticValidationError):
                PermitDecisionCommand(
                    application_id="app_synth_001",
                    outcome="approved",
                    final_ruling="approved",  # type: ignore[call-arg]
                )
            assert service.current_decision("app_synth_001") is None
    finally:
        factory.dispose()


def test_the_city_administrator_may_not_decide(seeded: Settings) -> None:
    """Configuration access never carries a business approval."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            administrator = context_for(session, "persona_city_administrator")
            service.evaluate("app_synth_001", reviewer)
            with pytest.raises(PermissionDeniedError):
                service.decide(
                    PermitDecisionCommand(
                        application_id="app_synth_001",
                        outcome="approved",
                        reason="Administrator attempt.",
                    ),
                    administrator,
                )
            assert service.current_decision("app_synth_001") is None
    finally:
        factory.dispose()


def test_an_unresolved_blocker_refuses_an_approval(seeded: Settings) -> None:
    """The expired contractor registration of D03 blocks the approval."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate("app_d03", reviewer)
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


def test_a_denial_is_allowed_even_with_an_unresolved_blocker(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate("app_d03", reviewer)
            result = service.decide(
                PermitDecisionCommand(
                    application_id="app_d03",
                    outcome="denied",
                    reason="The contractor registration has to be renewed.",
                    expected_evaluation_version=evaluation.version,
                ),
                reviewer,
            )
            assert not isinstance(result, ConflictResult)
            assert result.value.outcome == "denied"
            application = service.load_application("app_d03")
            assert application.status == "denied"
    finally:
        factory.dispose()


def test_a_stale_expected_version_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            service.evaluate("app_synth_001", reviewer)
            refused = service.decide(
                PermitDecisionCommand(
                    application_id="app_synth_001",
                    outcome="approved",
                    reason="Stale expectation.",
                    expected_application_version=99,
                ),
                reviewer)
            assert isinstance(refused, ConflictResult)
            assert refused.code == "version_conflict"
            assert service.current_decision("app_synth_001") is None
    finally:
        factory.dispose()


def test_a_reconfirmation_is_a_new_decision_version(seeded: Settings) -> None:
    """The earlier decision keeps its content and becomes superseded."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate("app_synth_001", reviewer)
            first = service.decide(
                PermitDecisionCommand(
                    application_id="app_synth_001",
                    outcome="approved",
                    reason="Fictional demonstration approval.",
                    expected_evaluation_version=evaluation.version,
                ),
                reviewer,
            )
            assert not isinstance(first, ConflictResult)

            # The decision goes stale and the application is evaluated again.
            decision = service.current_decision("app_synth_001")
            assert decision is not None
            decision.stale = True
            session.flush()
            second_evaluation = service.evaluate("app_synth_001", reviewer)

            confirmed = service.reconfirm(
                PermitDecisionCommand(
                    application_id="app_synth_001",
                    outcome="approved",
                    reason="Fictional reconfirmation.",
                    expected_evaluation_version=second_evaluation.version,
                ),
                reviewer,
            )
            assert not isinstance(confirmed, ConflictResult)
            assert confirmed.value.decision_id != first.value.decision_id
            assert confirmed.value.decision_type == "reconfirmation"
            assert confirmed.value.evaluation_id == second_evaluation.evaluation_id
            assert confirmed.value.stale is False

            stored = session.execute(
                select(permit.Decision).where(
                    permit.Decision.id == first.value.decision_id
                )
            ).scalar_one()
            assert stored.status == "superseded"
            assert stored.outcome == "approved"
            assert stored.reason == "Fictional demonstration approval."
            assert stored.decided_by_actor_id == "persona_permit_reviewer"
    finally:
        factory.dispose()
