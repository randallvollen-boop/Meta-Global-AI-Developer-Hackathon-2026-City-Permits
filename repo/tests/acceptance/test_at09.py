"""AT09: pending case impact.

A change to a required identity invalidates the pending work it affects and
nothing else.  An approved but unissued case becomes stale, revalidation
alone does not restore the approval, and an authorized reviewer has to
reconfirm the decision against the current versions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import ValidationError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import finance, permit, registry
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.decisions import PermitDecisionCommand
from acme_city.permits.impact import ChangeImpactCommand, ImpactService
from acme_city.permits.issuance import IssuePermitCommand, PermitIssuanceService
from acme_city.permits.service import PermitService

DECIDED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at09.db'}",
            "ACME_SECRET_KEY": "at09-pending-impact-secret-value",
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


def test_a_change_before_review_invalidates_only_the_affected_case(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            steward = context_for(session, "persona_data_steward")

            affected = service.evaluate("app_synth_001", reviewer)
            unrelated = service.evaluate("app_d02", reviewer)

            summary = ImpactService(session).apply_change(
                ChangeImpactCommand(
                    kind="party",
                    identifier="party_cedarline",
                    reason="The canonical record of the applicant was corrected.",
                ),
                steward,
            )
            touched = {case.application_id for case in summary.affected}
            assert "app_synth_001" in touched
            assert "app_d02" not in touched
            assert "SYN-APP-002" in summary.unchanged_applications

            stored = session.execute(
                select(permit.Evaluation).where(
                    permit.Evaluation.id == affected.evaluation_id
                )
            ).scalar_one()
            assert stored.stale is True

            other = session.execute(
                select(permit.Evaluation).where(
                    permit.Evaluation.id == unrelated.evaluation_id
                )
            ).scalar_one()
            assert other.stale is False
            assert other.status == "current"
    finally:
        factory.dispose()


def test_an_approval_becomes_stale_and_needs_a_reconfirmation(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            approve_links(session)
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            steward = context_for(session, "persona_data_steward")

            evaluation = service.evaluate("app_synth_001", reviewer)
            decided = service.decide(
                PermitDecisionCommand(
                    application_id="app_synth_001",
                    outcome="approved",
                    reason="Fictional demonstration approval.",
                    expected_evaluation_version=evaluation.version,
                ),
                reviewer,
            )
            assert decided.value.outcome == "approved"

            # The identity the case depends on changes.
            party = session.execute(
                select(registry.Party).where(registry.Party.id == "party_cedarline")
            ).scalar_one()
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
            decision = service.current_decision("app_synth_001")
            assert decision is not None
            assert decision.stale is True

            # Revalidation alone does not restore the approval.
            revalidated = service.evaluate("app_synth_001", reviewer)
            assert revalidated.evaluation_id != evaluation.evaluation_id
            still_stale = service.current_decision("app_synth_001")
            assert still_stale is not None
            assert still_stale.stale is True

            # The issuance is held until the reviewer reconfirms.
            application = service.load_application("app_synth_001")
            with pytest.raises(ValidationError):
                PermitIssuanceService(session).issue(
                    IssuePermitCommand(
                        application_id="app_synth_001",
                        decision_id=still_stale.id,
                        expected_application_version=application.version,
                        expected_decision_version=still_stale.version,
                        command_key="issue:at09:held",
                    ),
                    reviewer,
                )

            # The reconfirmation is a new decision version.
            confirmed = service.reconfirm(
                PermitDecisionCommand(
                    application_id="app_synth_001",
                    outcome="approved",
                    reason="Fictional reconfirmation against the current versions.",
                    expected_evaluation_version=revalidated.version,
                ),
                reviewer,
            )
            assert confirmed.value.decision_id != decided.value.decision_id
            assert confirmed.value.evaluation_id == revalidated.evaluation_id
            assert confirmed.value.stale is False
            previous = session.execute(
                select(permit.Decision).where(
                    permit.Decision.id == decided.value.decision_id
                )
            ).scalar_one()
            assert previous.status == "superseded"
            assert previous.outcome == "approved"
            assert previous.reason == "Fictional demonstration approval."
    finally:
        factory.dispose()
