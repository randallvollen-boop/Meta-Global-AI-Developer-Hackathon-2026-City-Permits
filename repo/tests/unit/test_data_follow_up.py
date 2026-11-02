"""An open parcel or identity link does not refuse a decision.

The case shows Data follow-up, a parcel rule that could not run needs an
exception reason, issuance still waits for the fee, and the Data Steward can
close the link after the permit is issued.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import ValidationError
from acme_city.core.results import ConflictResult
from acme_city.finance.schemas import AllocationCommand, AssessmentCommand, PaymentEventCommand
from acme_city.finance.service import FinanceService
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.gis.matching import ParcelMatchService
from acme_city.permits.decisions import (
    DATA_FOLLOW_UP_STATEMENT,
    PermitDecisionCommand,
    PermitDecisionService,
)
from acme_city.permits.issuance import IssuePermitCommand, PermitIssuanceService
from acme_city.permits.schemas import SubmitApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.persistence.models import audit, finance, gis, permit, registry
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

DECIDED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
REVIEWER = "persona_permit_reviewer"
STEWARD = "persona_data_steward"
ADMIN = "persona_city_administrator"
FLOOD_TITLE = "Flood zone"
REAR_FACTS = {
    "parcel_number": "ACME-P-1001",
    "project_description": "6 ft rear-yard fence",
    "valuation": "1200.00",
    "height_ft": 6,
    "setback_ft": 2,
    "structure_kind": "fence",
    "location": "side_rear",
    "submitted_parcel": "ACME-P-1001",
    "submitted_site_text": "400 Lantern Row, Suite 2, ACME City",
}


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'follow-up.db'}",
            "ACME_SECRET_KEY": "data-follow-up-test-secret-value",
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


def open_parcel_case(session) -> permit.Application:
    """Submit a passing rear fence whose parcel link is still proposed."""
    service = PermitService(session)
    view = service.submit(
        SubmitApplicationCommand(
            permit_type_key="deck_fence",
            facts=dict(REAR_FACTS),
            applicant_party_id="party_cedarline",
        ),
        context_for(session, STEWARD),
    )
    application = service.load_application(view.application_id)
    session.add(
        registry.Crosswalk(
            id=f"crosswalk_{application.id}",
            entity_id="party_cedarline",
            entity_type="party",
            source_system_id="permitting",
            source_dataset_key="applicant_profiles",
            source_record_id=f"PER-{application.id}",
            link_status="approved",
            decision="Approved by the data steward.",
            decision_actor_id=STEWARD,
            decided_at=DECIDED_AT,
        )
    )
    session.add(
        gis.ApplicationParcelMatch(
            id=f"pmatch_{application.id}",
            application_id=application.id,
            correlation_id=application.correlation_id,
            version=1,
            submitted_text="403 Lantern Row",
            matched_address="403 Lantern Row",
            address_id="address_400_lantern_unit_2",
            parcel_id="parcel_1001",
            parcel_number="ACME-P-1001",
            score=100.0,
            locator_status="M",
            method="locator",
            link_state="proposed",
            note="One candidate scored above the threshold.",
            proposed_by=STEWARD,
        )
    )
    session.flush()
    return application


def publish_flood_rule(session) -> None:
    """Publish a flood-zone rule that can run only from a confirmed parcel."""
    permit_type = session.execute(
        select(permit.PermitType).where(permit.PermitType.key == "deck_fence")
    ).scalar_one()
    session.add(
        finance.RuleVersion(
            id="rulever_flood_unchecked",
            rule_id="FZ-1",
            permit_type_id=permit_type.id,
            kind="executable",
            title=FLOOD_TITLE,
            citation="ACME Code §14-410",
            field_path="parcel_flood_zone",
            operator="equals",
            limit_value="X",
            on_violate="review",
            message="The flood zone of the parcel needs a review.",
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            status="published",
            author_actor_id=STEWARD,
            approver_actor_id=ADMIN,
        )
    )
    session.flush()


def decide(session, application_id: str, evaluation_version: int, **fields):
    """Record a decision against the versions the reviewer just read."""
    service = PermitService(session)
    application = service.load_application(application_id)
    return PermitDecisionService(session).decide(
        PermitDecisionCommand(
            application_id=application_id,
            expected_application_version=application.version,
            expected_evaluation_version=evaluation_version,
            **fields,
        ),
        context_for(session, REVIEWER),
    )


def test_an_open_parcel_link_does_not_block_the_decision_and_can_close_later(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            application = open_parcel_case(session)
            application_id = application.id
            reviewer = context_for(session, REVIEWER)
            evaluation = PermitService(session).evaluate(application_id, reviewer)
            stored = PermitService(session).current_evaluation(application_id)
            assert stored is not None
            codes = {
                blocker.code
                for blocker in PermitDecisionService(session).blockers(application, stored)
            }
            assert codes == {"parcel_link_unapproved"}
            result = decide(
                session,
                application_id,
                evaluation.version,
                outcome="approved",
                reason="The rear fence complies.",
            )
            assert not isinstance(result, ConflictResult)
            assert result.value.outcome == "approved"
            follow_up = result.value.input_versions["data_follow_up"]
            assert follow_up["statement"] == DATA_FOLLOW_UP_STATEMENT
            assert "exception" not in result.value.input_versions
            event = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "permit.decide",
                    audit.AuditEvent.target_id == result.value.decision_id,
                )
            ).scalar_one()
            assert event.reason == DATA_FOLLOW_UP_STATEMENT
            assert event.metadata_json["data_follow_up"] == DATA_FOLLOW_UP_STATEMENT
    finally:
        factory.dispose()

    app = create_app(seeded)
    with TestClient(app) as client:
        chosen = client.post("/api/session/select", json={"actor_id": REVIEWER})
        assert chosen.status_code == 200, chosen.text
        page = client.get(f"/permits/{application_id}")
        assert page.status_code == 200, page.text
        assert 'data-testid="data-follow-up">Data follow-up' in page.text

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            reviewer = context_for(session, REVIEWER)
            administrator = context_for(session, ADMIN)
            permits = PermitService(session)
            issuance = PermitIssuanceService(session)
            application = permits.load_application(application_id)
            decision = permits.current_decision(application_id)
            assert decision is not None
            with pytest.raises(ValidationError) as raised:
                issuance.issue(
                    IssuePermitCommand(
                        application_id=application_id,
                        decision_id=decision.id,
                        expected_application_version=application.version,
                        expected_decision_version=decision.version,
                        command_key="issue:g29:before-fee",
                    ),
                    reviewer,
                )
            codes = {item["code"] for item in raised.value.details["blockers"]}
            assert "no_current_assessment" in codes
            assert "parcel_link_unapproved" not in codes

            assessment = FinanceService(session).assess(
                AssessmentCommand(
                    application_id=application_id,
                    expected_application_version=application.version,
                    reason="assess the fence fee",
                ),
                administrator,
            )
            payment = FinanceService(session).import_payment(
                PaymentEventCommand(
                    source_transaction_id="ERP-TXN-G29-1",
                    source_event_id="ERP-EVT-G29-1",
                    event_type="settled",
                    amount=assessment.assessed_total,
                    currency="USD",
                    party_id="party_cedarline",
                ),
                administrator,
            )
            FinanceService(session).allocate(
                AllocationCommand(
                    payment_id=payment.payment_id,
                    assessment_id=assessment.assessment_id,
                    amount=assessment.assessed_total,
                    idempotency_key="alloc:g29:open-link",
                    reason="settle the fence fee",
                ),
                administrator,
            )
            application = permits.load_application(application_id)
            decision = permits.current_decision(application_id)
            assert decision is not None
            issued = issuance.issue(
                IssuePermitCommand(
                    application_id=application_id,
                    decision_id=decision.id,
                    expected_application_version=application.version,
                    expected_decision_version=decision.version,
                    command_key="issue:g29:after-fee",
                    reason="issue while the parcel link stays open",
                ),
                reviewer,
            )
            assert not isinstance(issued, ConflictResult)
            assert permits.load_application(application_id).status == "issued"
            match = ParcelMatchService(session).for_application(application_id)
            assert match is not None and match.link_state == "proposed"
            ParcelMatchService(session).decide_link(
                application_id,
                decision="approve",
                reason="the property was confirmed after the permit was issued",
                expected_version=match.version,
                actor=context_for(session, STEWARD),
            )
            closed = ParcelMatchService(session).for_application(application_id)
            assert closed is not None and closed.link_state == "approved"
    finally:
        factory.dispose()


def test_an_unchecked_parcel_rule_needs_an_exception_reason(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            publish_flood_rule(session)
            application = open_parcel_case(session)
            application_id = application.id
            reviewer = context_for(session, REVIEWER)
            evaluation = PermitService(session).evaluate(application_id, reviewer)
            stored = PermitService(session).current_evaluation(application_id)
            assert stored is not None
            flood = next(row for row in stored.results or [] if row.get("rule_id") == "FZ-1")
            assert flood["reason"] == "parcel_not_confirmed"
            with pytest.raises(ValidationError) as raised:
                decide(
                    session,
                    application_id,
                    evaluation.version,
                    outcome="approved",
                    reason="The rear fence complies.",
                )
            message = str(raised.value)
            assert FLOOD_TITLE in message
            assert "not checked" in message
            assert "exception reason" in message
            assert "unresolved blockers" not in message
            assert PermitService(session).current_decision(application_id) is None
            result = decide(
                session,
                application_id,
                evaluation.version,
                outcome="approved",
                reason="The rear fence complies.",
                exception_reason="The parcel is outside the flood zone.",
            )
            assert not isinstance(result, ConflictResult)
            recorded = result.value.input_versions["exception"]
            assert recorded["statement"] == f"Approved as an exception to {FLOOD_TITLE}"
            assert recorded["rules"] == [
                {"rule_id": "FZ-1", "title": FLOOD_TITLE, "status": "not_checked"}
            ]
            assert result.value.input_versions["data_follow_up"]["statement"] == (
                DATA_FOLLOW_UP_STATEMENT
            )
    finally:
        factory.dispose()

    app = create_app(seeded)
    with TestClient(app) as client:
        chosen = client.post("/api/session/select", json={"actor_id": REVIEWER})
        assert chosen.status_code == 200, chosen.text
        page = client.get(f"/permits/{application_id}")
        assert page.status_code == 200, page.text
        assert 'data-testid="check-plain">Not checked' in page.text
        assert FLOOD_TITLE in page.text
        assert f"Approved as an exception to {FLOOD_TITLE}" in page.text
