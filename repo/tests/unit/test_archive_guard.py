"""The archive guard, path by path.

Archiving a case is a soft delete.  Every service path that could change
the case asks the guard first, so an archived case cannot be reopened by a
revision, a document, an evaluation, an agent run, a recommendation, a
parcel operation, a finance assessment or a portal upload.  Only an
authorized, version-checked restore reactivates it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.agents.control import AgentControlService
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import ValidationError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import finance, permit
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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'archive.db'}",
            "ACME_SECRET_KEY": "archive-test-secret-value",
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


def archived_case(
    session, *, status: str = "submitted", applicant_party_id: str = "party_cedarline"
) -> permit.Application:
    """Submit one case and archive it."""
    service = PermitService(session)
    steward = context_for(session, "persona_data_steward")
    view = service.submit(
        SubmitApplicationCommand(
            permit_type_key="com_ti",
            facts=dict(FACTS),
            applicant_party_id=applicant_party_id,
        ),
        steward,
    )
    application = service.load_application(view.application_id)
    application.status = status
    session.flush()
    administrator = context_for(session, "persona_city_administrator")
    LifecycleService(session).archive(
        application_id=application.id,
        reason_code="ARCHIVE_DUPLICATE_RECORD",
        reason="The case repeats another record.",
        actor=administrator,
        expected_version=application.version,
    )
    session.flush()
    return application


def test_an_archived_case_refuses_a_revision(seeded: Settings) -> None:
    """Path 1: the API revision path."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = archived_case(session)
            steward = context_for(session, "persona_data_steward")
            from acme_city.permits.schemas import ReviseApplicationCommand

            with pytest.raises(ValidationError) as error:
                PermitService(session).revise(
                    ReviseApplicationCommand(
                        application_id=application.id,
                        facts={"valuation": "60000.00"},
                        reason="A fictional correction.",
                    ),
                    steward,
                )
            assert "archived" in str(error.value)
    finally:
        factory.dispose()


def test_an_archived_case_refuses_a_document(seeded: Settings) -> None:
    """Path 2: the document store."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = archived_case(session)
            steward = context_for(session, "persona_data_steward")
            from acme_city.documents.service import DocumentService, StoreDocumentCommand

            with pytest.raises(ValidationError) as error:
                DocumentService(session).store_version(
                    StoreDocumentCommand(
                        application_id=application.id,
                        document_type="site_plan",
                        filename="archived-plan.pdf",
                        media_type="application/pdf",
                        content=b"%PDF-1.4 fictional",
                    ),
                    steward,
                )
            assert "archived" in str(error.value)
    finally:
        factory.dispose()


def test_an_archived_case_refuses_an_evaluation(seeded: Settings) -> None:
    """Path 3: the evaluation path, which reopens a non-issued case."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = archived_case(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            with pytest.raises(ValidationError) as error:
                PermitService(session).evaluate(application.id, reviewer)
            assert "archived" in str(error.value)
    finally:
        factory.dispose()


def test_an_archived_case_refuses_the_intake_agent(seeded: Settings) -> None:
    """Path 4: the intake agent accepts any application id."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = archived_case(session)
            AgentControlService(session).set_mode(
                "intake", "awake", context_for(session, "persona_city_administrator")
            )
            from acme_city.agents.intake import IntakeAgent

            with pytest.raises(ValidationError) as error:
                IntakeAgent(session).run(application.id, triggered_by="persona_data_steward")
            assert "archived" in str(error.value)
    finally:
        factory.dispose()


def test_an_archived_case_refuses_the_adjudication_agent(seeded: Settings) -> None:
    """Path 5: the adjudication agent accepts any application id."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = archived_case(session, status="ready_for_review")
            AgentControlService(session).set_mode(
                "adjudication", "awake", context_for(session, "persona_city_administrator")
            )
            from acme_city.agents.adjudication import AdjudicationAgent

            with pytest.raises(ValidationError) as error:
                AdjudicationAgent(session).run(
                    application.id, triggered_by="persona_permit_reviewer"
                )
            assert "archived" in str(error.value)
    finally:
        factory.dispose()


def test_an_archived_case_refuses_a_recommendation(seeded: Settings) -> None:
    """Path 6: the recommendation confirm and revert paths."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = archived_case(session, status="under_review")
            recommendation = permit.Recommendation(
                id="recommendation_archived_1",
                application_id=application.id,
                proposed_outcome="approve",
                status="pending",
                version=1,
            )
            session.add(recommendation)
            session.flush()
            from acme_city.agents.recommendation import confirm, revert

            reviewer = context_for(session, "persona_permit_reviewer")
            with pytest.raises(ValidationError) as error:
                confirm(
                    session,
                    recommendation_id=recommendation.id,
                    application_id=application.id,
                    actor=reviewer,
                    expected_application_version=application.version,
                )
            assert "archived" in str(error.value)
            with pytest.raises(ValidationError) as error:
                revert(
                    session,
                    recommendation_id=recommendation.id,
                    application_id=application.id,
                    reason="A fictional reason.",
                    actor=reviewer,
                )
            assert "archived" in str(error.value)
    finally:
        factory.dispose()


def test_an_archived_case_refuses_a_parcel_operation(seeded: Settings) -> None:
    """Path 7: the parcel operations."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = archived_case(session)
            from acme_city.gis.matching import ParcelMatchService

            service = ParcelMatchService(session)
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError) as error:
                service.locate(application, steward)
            assert "archived" in str(error.value)
            with pytest.raises(ValidationError) as error:
                service.decide_link(
                    application.id,
                    decision="approve",
                    reason="A fictional reason.",
                    expected_version=None,
                    actor=steward,
                )
            assert "archived" in str(error.value)
            with pytest.raises(ValidationError) as error:
                service.find_by_number(
                    application.id,
                    parcel_number="ACME-P-1001",
                    reason="A fictional reason.",
                    expected_version=None,
                    actor=steward,
                )
            assert "archived" in str(error.value)
    finally:
        factory.dispose()


def test_an_archived_case_refuses_a_finance_assessment(seeded: Settings) -> None:
    """Path 8: the finance paths."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = archived_case(session)
            from acme_city.finance.schemas import AssessmentCommand
            from acme_city.finance.service import FinanceService

            administrator = context_for(session, "persona_city_administrator")
            with pytest.raises(ValidationError) as error:
                FinanceService(session).assess(
                    AssessmentCommand(
                        application_id=application.id,
                        valuation="50000.00",
                        reason="A fictional assessment.",
                    ),
                    administrator,
                )
            assert "archived" in str(error.value)
    finally:
        factory.dispose()


def test_an_archived_case_refuses_a_portal_upload(seeded: Settings) -> None:
    """Path 9: the portal upload and the portal resubmission."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = archived_case(
                session, status="needs_information", applicant_party_id="party_applicant_1"
            )
            from acme_city.applicant_portal.service import PortalService

            applicant = context_for(session, "persona_applicant")
            service = PortalService(session)
            with pytest.raises(ValidationError) as error:
                service.revise_documents(
                    application.id,
                    [("site_plan", "late-plan.txt", b"a late plan")],
                    applicant,
                )
            assert "archived" in str(error.value)
            with pytest.raises(ValidationError) as error:
                service.resubmit(
                    application.id,
                    applicant,
                    uploads=[],
                    answers={},
                    expected_version=application.version,
                )
            assert "archived" in str(error.value)
    finally:
        factory.dispose()


def test_a_restore_reactivates_the_case(seeded: Settings) -> None:
    """Only a version-checked restore reactivates an archived case."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = archived_case(session)
            administrator = context_for(session, "persona_city_administrator")
            lifecycle = LifecycleService(session)
            with pytest.raises(ValidationError):
                lifecycle.restore(
                    application_id=application.id,
                    actor=administrator,
                    expected_version=None,
                )
            with pytest.raises(ValidationError):
                lifecycle.restore(
                    application_id=application.id,
                    actor=administrator,
                    expected_version=application.version + 7,
                )
            lifecycle.restore(
                application_id=application.id,
                actor=administrator,
                expected_version=application.version,
            )
            session.refresh(application)
            assert application.status == "submitted"
            # The case may be revised again once it is restored.
            from acme_city.permits.schemas import ReviseApplicationCommand

            steward = context_for(session, "persona_data_steward")
            PermitService(session).revise(
                ReviseApplicationCommand(
                    application_id=application.id,
                    facts={"valuation": "60000.00"},
                    reason="A fictional correction.",
                ),
                steward,
            )
    finally:
        factory.dispose()


def test_an_archived_case_is_not_in_the_active_queue(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            archived_case(session)
            from acme_city.ui.view_models import work_queue

            steward = context_for(session, "persona_data_steward")
            queue = work_queue(session, steward)
            references = {
                item["id"]
                for item in queue["entries"]
                if item.get("kind") == "application"
            }
            assert "SYN-APP-011" not in references
    finally:
        factory.dispose()


def test_an_archived_case_refuses_the_bulk_intake_processing(
    seeded: Settings,
) -> None:
    """Path 12: the bulk processing action of phase 3b asks the guard."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = archived_case(session)
            AgentControlService(session).set_mode(
                "intake", "awake", context_for(session, "persona_city_administrator")
            )
            from acme_city.permits.bulk import Selection, process_selected

            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError) as error:
                process_selected(
                    session,
                    actor=steward,
                    selections=[Selection(application.id, application.version)],
                )
            assert "archived" in str(error.value)
    finally:
        factory.dispose()
