"""The conditions of an approval travel with the decision.

An approval with conditions is an ``approved`` decision that carries a
non-empty list of conditions.  The conditions survive the reconfirmation,
the issuance and the immutable permit artifact, and the applicant reads them
on the tracker.
"""
# REQUIRES: PER-04, UX-02, SEC-03
# The conditions of an approval are carried through the decision, the
# reconfirmation, the applicant tracker and the permit artifact.

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import ValidationError
from acme_city.finance.schemas import AllocationCommand, AssessmentCommand
from acme_city.finance.service import FinanceService
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import finance, permit, registry
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.decisions import PermitDecisionCommand
from acme_city.permits.impact import ChangeImpactCommand, ImpactService
from acme_city.permits.issuance import (
    IssuePermitCommand,
    PermitIssuanceService,
    render_permit_artifact,
)
from acme_city.permits.service import PermitService

DECIDED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)

#: The conditions of the fictional approval.
CONDITIONS = [
    "The fence may not be higher than 4 ft.",
    "A readable copy of the site plan must be on file.",
]


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'conditions.db'}",
            "ACME_SECRET_KEY": "conditions-test-secret-value",
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


def approve_links(session) -> None:
    """Record the canonical links a steward would have approved."""
    for party_id in ("party_cedarline", "party_ironvale"):
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


def test_an_approval_with_conditions_is_an_approved_decision(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            permits = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = permits.evaluate("app_synth_001", reviewer)
            result = permits.decide(
                PermitDecisionCommand(
                    application_id="app_synth_001",
                    outcome="approved_with_conditions",
                    reason="Fictional demonstration approval with conditions.",
                    conditions=list(CONDITIONS),
                    expected_evaluation_version=evaluation.version,
                ),
                reviewer,
            )
            decision = result.value
            # The recorded outcome is unchanged: an approval with conditions is
            # an approved decision that carries conditions.
            assert decision.outcome == "approved"
            assert decision.conditions == CONDITIONS
            stored = permits.current_decision("app_synth_001")
            assert stored is not None
            assert stored.conditions == CONDITIONS
    finally:
        factory.dispose()


def test_an_approval_with_conditions_needs_a_condition(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            permits = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = permits.evaluate("app_synth_001", reviewer)
            with pytest.raises(ValidationError):
                permits.decide(
                    PermitDecisionCommand(
                        application_id="app_synth_001",
                        outcome="approved_with_conditions",
                        reason="Fictional demonstration approval with conditions.",
                        conditions=[],
                        expected_evaluation_version=evaluation.version,
                    ),
                    reviewer,
                )
            assert permits.current_decision("app_synth_001") is None
    finally:
        factory.dispose()


def test_every_outcome_needs_a_rationale(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            permits = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = permits.evaluate("app_synth_001", reviewer)
            with pytest.raises(ValidationError) as raised:
                permits.decide(
                    PermitDecisionCommand(
                        application_id="app_synth_001",
                        outcome="approved",
                        reason="   ",
                        expected_evaluation_version=evaluation.version,
                    ),
                    reviewer,
                )
            assert "rationale" in str(raised.value)
            assert permits.current_decision("app_synth_001") is None
    finally:
        factory.dispose()


def test_the_conditions_survive_the_reconfirmation_and_the_artifact(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            permits = PermitService(session)
            finance_service = FinanceService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            steward = context_for(session, "persona_data_steward")
            administrator = context_for(session, "persona_city_administrator")

            evaluation = permits.evaluate("app_synth_001", reviewer)
            first = permits.decide(
                PermitDecisionCommand(
                    application_id="app_synth_001",
                    outcome="approved_with_conditions",
                    reason="Fictional demonstration approval with conditions.",
                    conditions=list(CONDITIONS),
                    expected_evaluation_version=evaluation.version,
                ),
                reviewer,
            )
            assert first.value.conditions == CONDITIONS

            # The identity the case depends on changes, so the decision goes
            # stale and has to be reconfirmed.
            party = session.get(registry.Party, "party_cedarline")
            party.version += 1
            session.flush()
            ImpactService(session).apply_change(
                ChangeImpactCommand(
                    kind="party",
                    identifier="party_cedarline",
                    reason="The canonical record of the applicant was corrected.",
                ),
                steward,
            )
            stale = permits.current_decision("app_synth_001")
            assert stale is not None and stale.stale is True

            revalidated = permits.evaluate("app_synth_001", reviewer)
            confirmed = permits.reconfirm(
                PermitDecisionCommand(
                    application_id="app_synth_001",
                    outcome="approved_with_conditions",
                    reason="Fictional reconfirmation against the current versions.",
                    conditions=list(CONDITIONS),
                    expected_evaluation_version=revalidated.version,
                ),
                reviewer,
            )
            # The reconfirmation is a new decision version and it carries the
            # conditions of the approval.
            assert confirmed.value.decision_id != first.value.decision_id
            assert confirmed.value.conditions == CONDITIONS

            assessment = finance_service.assess(
                AssessmentCommand(application_id="app_synth_001"), administrator
            )
            finance_service.allocate(
                AllocationCommand(
                    payment_id="payment_d01_settled",
                    assessment_id=assessment.assessment_id,
                    amount="150.00",
                    idempotency_key="alloc:test:conditions",
                ),
                administrator,
            )

            application = permits.load_application("app_synth_001")
            decision = permits.current_decision("app_synth_001")
            assert decision is not None
            issued = PermitIssuanceService(session).issue(
                IssuePermitCommand(
                    application_id="app_synth_001",
                    decision_id=decision.id,
                    expected_application_version=application.version,
                    expected_decision_version=decision.version,
                    command_key="issue:test:conditions",
                ),
                reviewer,
            )
            permit_id = issued.value.permit_id
            artifact = render_permit_artifact(session, permit_id).decode("utf-8")
            # The artifact shows the conditions of the approval.
            for condition in CONDITIONS:
                assert condition in artifact
            snapshot = issued.value.snapshot
            assert snapshot["decision"]["conditions"] == CONDITIONS
    finally:
        factory.dispose()


def test_the_applicant_reads_the_conditions_on_the_tracker(seeded: Settings) -> None:
    from acme_city.applicant_portal.service import PortalService

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            # The D05 case is the one the Applicant persona owns.  Its
            # conditions are recorded directly here: the decision service
            # itself is proven above.
            session.add(
                permit.Decision(
                    id="decision_conditions_tracker",
                    application_id="app_d05",
                    evaluation_id=None,
                    decision_type="review",
                    outcome="approved",
                    decided_by_actor_id="persona_permit_reviewer",
                    decided_at=DECIDED_AT,
                    reason="Fictional demonstration approval with conditions.",
                    status="current",
                    stale=False,
                    conditions=list(CONDITIONS),
                    version=1,
                )
            )
            session.flush()
            applicant = context_for(session, "persona_applicant")
            tracked = PortalService(session).track("SYN-APP-005", applicant)
            assert tracked is not None
            assert tracked["decision_conditions"] == CONDITIONS
    finally:
        factory.dispose()
