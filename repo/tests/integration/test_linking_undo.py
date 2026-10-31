"""Every applied party link is reviewable and reversible.

The worker applies a party link when the policy of the City allows it.  The
link is then a reviewable item of the queue, and a steward may take it back
with a reason.  The trail keeps both events: the application is never
deleted, and a link that a person changed since the application is not taken
back silently.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.agents import linking
from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.core.errors import ConflictError, PermissionDeniedError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.ingestion.schemas import IngestCommand, SourceRecordCommand
from acme_city.ingestion.service import IngestionService
from acme_city.persistence.models import audit, change, registry, registry_automation, source
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.registry import automation
from acme_city.ui.router import router as ui_router

PAYLOAD = {
    "party_ref": "party_applicant_1",
    "display_name": "Demo Applicant",
    "contact_email": "demo.applicant+autolink@example.invalid",
    "contact_phone": "+1-555-0141",
    "preferred_contact": "email",
}

#: The person who authorizes the automation and reviews its links.
STEWARD = ActorContext(actor_id="persona_data_steward", role_ids=frozenset())

#: The reason a steward gives when a link is taken back.
UNDO_REASON = "The record named the wrong master record."


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'linking-undo.db'}",
            "ACME_SECRET_KEY": "linking-undo-test-secret",
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


@pytest.fixture()
def http_client(seeded: Settings):
    """Return a client of the interface of the demonstration."""
    app = create_app(seeded)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def _csrf(client: TestClient) -> str:
    """Return the form token of the current session."""
    body = client.get("/steward/automation").text
    match = re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert match, "the page carries a form token"
    return match.group(1)


def _prepare(factory: SessionFactory, *, mode: str = "active") -> None:
    """Activate a policy and accept a source version, which queues the work."""
    with transaction(factory) as session:
        session.add(
            registry_automation.RegistryAutomationPolicy(
                id="policy_undo_1",
                version=1,
                mode=mode,
                status="active",
                matcher_version="registry-candidates-v1",
                thresholds={},
                source_scopes=["applicant_profiles"],
                reason="exercise the reversible links",
                recorded_by_actor_id="persona_data_steward",
                activated_at=datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
            )
        )
    intake = IngestCommand(
        source_system_id="permitting",
        dataset_key="applicant_profiles",
        records=[
            SourceRecordCommand(
                source_record_id="PER-AP-0001",
                source_record_version="4",
                payload=PAYLOAD,
                source_updated_at=datetime(2026, 10, 29, 12, 1, tzinfo=UTC),
            )
        ],
    )
    with transaction(factory) as session:
        service = IngestionService(session, registry_automation_mode="active")
        assert service.ingest(intake, STEWARD).accepted == 1


def _run_worker(factory: SessionFactory):
    """Process the queued work once and return the report."""
    with transaction(factory) as session:
        return linking.run_once(session)


def _application(factory: SessionFactory) -> registry_automation.RegistryAutomationApplication:
    """Return the recorded application of the database."""
    with transaction(factory) as session:
        rows = session.execute(
            select(registry_automation.RegistryAutomationApplication)
        ).scalars().all()
        assert len(rows) == 1
        return rows[0]


def test_the_worker_applies_an_eligible_party_link(seeded: Settings) -> None:
    """The worker applies the link and leaves a reviewable item behind."""
    factory = SessionFactory(seeded.database_url)
    try:
        _prepare(factory)
        report = _run_worker(factory)
        assert report.processed[0].decision == "auto_apply"

        application = _application(factory)
        assert application.status == "applied"
        assert application.applied_by_actor_id == linking.LINKING_ACTOR_ID

        with transaction(factory) as session:
            link = session.get(registry.Crosswalk, application.crosswalk_id)
            assert link is not None
            assert link.link_status == "approved"
            assert link.entity_id == "party_applicant_1"
            tasks = session.execute(
                select(change.ReviewTask).where(
                    change.ReviewTask.task_type == automation.REVIEW_TASK_TYPE
                )
            ).scalars().all()
            assert len(tasks) == 1
            assert tasks[0].status == "open"
            assert tasks[0].assignee_actor_id == "persona_data_steward"
    finally:
        factory.dispose()


def test_the_steward_takes_the_link_back(seeded: Settings) -> None:
    """The undo removes the link and keeps the event that applied it."""
    factory = SessionFactory(seeded.database_url)
    try:
        _prepare(factory)
        _run_worker(factory)
        application = _application(factory)
        with transaction(factory) as session:
            recorded = automation.reverse_application(
                session,
                application_id=application.id,
                reason=UNDO_REASON,
                actor=STEWARD,
            )
            assert recorded.status == "reversed"
            assert recorded.reviewed_by_actor_id == "persona_data_steward"
            assert recorded.review_note == UNDO_REASON

        with transaction(factory) as session:
            link = session.get(registry.Crosswalk, application.crosswalk_id)
            assert link is not None
            assert link.link_status == "removed"
            assert link.decision == UNDO_REASON
            assert link.decision_actor_id == "persona_data_steward"
            assert link.valid_to is not None

            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action.in_(
                        [automation.APPLY_ACTION, "registry.crosswalk.remove_automatic"]
                    )
                )
            ).scalars().all()
            actions = [event.action for event in events]
            assert automation.APPLY_ACTION in actions
            assert "registry.crosswalk.remove_automatic" in actions
            assert len(events) == 2

            stored = session.get(
                registry_automation.RegistryAutomationApplication, application.id
            )
            assert stored is not None
            assert stored.status == "reversed"

            tasks = session.execute(
                select(change.ReviewTask).where(
                    change.ReviewTask.task_type == automation.REVIEW_TASK_TYPE
                )
            ).scalars().all()
            assert len(tasks) == 1
            assert tasks[0].status == "resolved"
    finally:
        factory.dispose()


def test_the_take_back_hands_the_prior_proposal_back(seeded: Settings) -> None:
    """A link that was applied on top of a proposal is handed back as it.

    The steward had an open proposal for the record.  The automation applied
    it, and the take back gives the proposal back instead of recording a
    decided removal that the steward can no longer answer.
    """
    factory = SessionFactory(seeded.database_url)
    try:
        _prepare(factory)
        with transaction(factory) as session:
            session.add(
                registry.Crosswalk(
                    id="crosswalk_proposal_1",
                    entity_id="party_applicant_1",
                    entity_type="party",
                    source_system_id="permitting",
                    source_dataset_key="applicant_profiles",
                    source_record_id="PER-AP-0001",
                    link_status="proposed",
                    decision=None,
                    decision_actor_id=None,
                    decided_at=None,
                    expected_version=None,
                    valid_from=None,
                    valid_to=None,
                    superseded_by_crosswalk_id=None,
                    scenario_id=None,
                )
            )
        _run_worker(factory)
        application = _application(factory)
        assert application.crosswalk_id == "crosswalk_proposal_1"
        assert application.before_state["link_status"] == "proposed"
        assert application.before_state["crosswalk_id"] == "crosswalk_proposal_1"
        with transaction(factory) as session:
            link = session.get(registry.Crosswalk, application.crosswalk_id)
            assert link is not None
            assert link.link_status == "approved"

        with transaction(factory) as session:
            recorded = automation.reverse_application(
                session,
                application_id=application.id,
                reason=UNDO_REASON,
                actor=STEWARD,
            )
            assert recorded.status == "reversed"

        with transaction(factory) as session:
            link = session.get(registry.Crosswalk, "crosswalk_proposal_1")
            assert link is not None
            assert link.link_status == "proposed"
            assert link.decision is None
            assert link.decision_actor_id is None
            assert link.decided_at is None
            assert link.valid_from is None
            assert link.valid_to is None
            links = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "PER-AP-0001"
                )
            ).scalars().all()
            assert len(links) == 1
    finally:
        factory.dispose()


def test_a_repeated_take_back_is_safe(seeded: Settings) -> None:
    """A link that was already taken back is not taken back twice."""
    factory = SessionFactory(seeded.database_url)
    try:
        _prepare(factory)
        _run_worker(factory)
        application = _application(factory)
        with transaction(factory) as session:
            automation.reverse_application(
                session,
                application_id=application.id,
                reason=UNDO_REASON,
                actor=STEWARD,
            )
        with transaction(factory) as session:
            again = automation.reverse_application(
                session,
                application_id=application.id,
                reason=UNDO_REASON,
                actor=STEWARD,
            )
            assert again.status == "reversed"
        with transaction(factory) as session:
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "registry.crosswalk.remove_automatic"
                )
            ).scalars().all()
            assert len(events) == 1
    finally:
        factory.dispose()


def test_a_stale_take_back_is_refused(seeded: Settings) -> None:
    """A link that changed since the application is not taken back silently."""
    factory = SessionFactory(seeded.database_url)
    try:
        _prepare(factory)
        _run_worker(factory)
        application = _application(factory)
        with pytest.raises(ConflictError):
            with transaction(factory) as session:
                automation.reverse_application(
                    session,
                    application_id=application.id,
                    reason=UNDO_REASON,
                    actor=STEWARD,
                    expected_version=99,
                )
        with transaction(factory) as session:
            link = session.get(registry.Crosswalk, application.crosswalk_id)
            assert link is not None
            assert link.link_status == "approved"
    finally:
        factory.dispose()


def test_the_review_records_the_person_who_looked(seeded: Settings) -> None:
    """A review keeps the link and records the person who looked at it."""
    factory = SessionFactory(seeded.database_url)
    try:
        _prepare(factory)
        _run_worker(factory)
        application = _application(factory)
        with transaction(factory) as session:
            recorded = automation.acknowledge_application(
                session,
                application_id=application.id,
                note="The master record is right.",
                actor=STEWARD,
            )
            assert recorded.status == "acknowledged"
            assert recorded.reviewed_by_actor_id == "persona_data_steward"
        with transaction(factory) as session:
            link = session.get(registry.Crosswalk, application.crosswalk_id)
            assert link is not None
            assert link.link_status == "approved"
            tasks = session.execute(
                select(change.ReviewTask).where(
                    change.ReviewTask.task_type == automation.REVIEW_TASK_TYPE
                )
            ).scalars().all()
            assert len(tasks) == 1
            assert tasks[0].status == "resolved"
    finally:
        factory.dispose()


def test_the_service_identity_may_not_take_a_link_back(seeded: Settings) -> None:
    """Only a person with the undo grant may reverse an applied link."""
    factory = SessionFactory(seeded.database_url)
    try:
        _prepare(factory)
        _run_worker(factory)
        application = _application(factory)
        with pytest.raises(PermissionDeniedError):
            with transaction(factory) as session:
                automation.reverse_application(
                    session,
                    application_id=application.id,
                    reason=UNDO_REASON,
                    actor=linking.service_actor(),
                )
        with transaction(factory) as session:
            link = session.get(registry.Crosswalk, application.crosswalk_id)
            assert link is not None
            assert link.link_status == "approved"
    finally:
        factory.dispose()


def test_a_policy_that_records_suggestions_applies_nothing(seeded: Settings) -> None:
    """A policy that only suggests never applies a link."""
    factory = SessionFactory(seeded.database_url)
    try:
        _prepare(factory, mode="suggestions")
        report = _run_worker(factory)
        assert report.processed[0].decision == "suggest"
        with transaction(factory) as session:
            applications = session.execute(
                select(registry_automation.RegistryAutomationApplication)
            ).scalars().all()
            assert applications == []
            links = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "PER-AP-0001"
                )
            ).scalars().all()
            assert links == []
    finally:
        factory.dispose()


def test_the_undo_needs_a_reason(seeded: Settings) -> None:
    """A removal always states why the link is taken back."""
    factory = SessionFactory(seeded.database_url)
    try:
        _prepare(factory)
        _run_worker(factory)
        application = _application(factory)
        with pytest.raises(Exception):
            with transaction(factory) as session:
                automation.reverse_application(
                    session,
                    application_id=application.id,
                    reason="   ",
                    actor=STEWARD,
                )
        with transaction(factory) as session:
            link = session.get(registry.Crosswalk, application.crosswalk_id)
            assert link is not None
            assert link.link_status == "approved"
    finally:
        factory.dispose()


def test_the_steward_takes_the_link_back_through_the_screen(
    seeded: Settings, http_client: TestClient
) -> None:
    """The undo action of the interface takes the link back."""
    factory = SessionFactory(seeded.database_url)
    try:
        _prepare(factory)
        _run_worker(factory)
        application = _application(factory)
        with transaction(factory) as session:
            link = session.get(registry.Crosswalk, application.crosswalk_id)
            assert link is not None
            version = link.version
        response = http_client.post(
            "/api/session/select", json={"actor_id": "persona_data_steward"}
        )
        assert response.status_code == 200
        posted = http_client.post(
            "/ui/actions/registry.automation.undo",
            data={
                "csrf_token": _csrf(http_client),
                "application_id": application.id,
                "expected_version": str(version),
                "reason": UNDO_REASON,
                "next": "/steward/automation",
            },
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        assert posted.status_code == 200, posted.text
        assert posted.json()["status"] == "accepted"
        with transaction(factory) as session:
            link = session.get(registry.Crosswalk, application.crosswalk_id)
            assert link is not None
            assert link.link_status == "removed"
            stored = session.get(
                registry_automation.RegistryAutomationApplication, application.id
            )
            assert stored is not None
            assert stored.status == "reversed"
    finally:
        factory.dispose()


def test_the_take_back_of_the_screen_needs_the_version_of_the_link(
    seeded: Settings, http_client: TestClient
) -> None:
    """A take back without the version of the link is refused."""
    factory = SessionFactory(seeded.database_url)
    try:
        _prepare(factory)
        _run_worker(factory)
        application = _application(factory)
        response = http_client.post(
            "/api/session/select", json={"actor_id": "persona_data_steward"}
        )
        assert response.status_code == 200
        posted = http_client.post(
            "/ui/actions/registry.automation.undo",
            data={
                "csrf_token": _csrf(http_client),
                "application_id": application.id,
                "reason": UNDO_REASON,
                "next": "/steward/automation",
            },
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        assert posted.status_code == 422, posted.text
        assert posted.json()["status"] == "denied"
        with transaction(factory) as session:
            link = session.get(registry.Crosswalk, application.crosswalk_id)
            assert link is not None
            assert link.link_status == "approved"
            stored = session.get(
                registry_automation.RegistryAutomationApplication, application.id
            )
            assert stored is not None
            assert stored.status == "applied"
    finally:
        factory.dispose()


def test_the_activate_action_offers_only_the_mode_of_the_screen(
    seeded: Settings, http_client: TestClient
) -> None:
    """A mode the screen does not offer is refused by the activate action."""
    factory = SessionFactory(seeded.database_url)
    try:
        response = http_client.post(
            "/api/session/select", json={"actor_id": "persona_data_steward"}
        )
        assert response.status_code == 200
        posted = http_client.post(
            "/ui/actions/registry.automation.activate",
            data={
                "csrf_token": _csrf(http_client),
                "mode": "suggestions",
                "source_scope": "applicant_profiles",
                "reason": "the steward wants suggestions only",
                "expected_version": "0",
                "next": "/steward/automation",
            },
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        assert posted.status_code == 422, posted.text
        assert posted.json()["status"] == "denied"
        with transaction(factory) as session:
            policies = session.execute(
                select(registry_automation.RegistryAutomationPolicy)
            ).scalars().all()
            assert policies == []
    finally:
        factory.dispose()


def test_the_reviewer_may_not_take_a_link_back(
    seeded: Settings, http_client: TestClient
) -> None:
    """The undo action is the grant of the Data Steward alone."""
    factory = SessionFactory(seeded.database_url)
    try:
        _prepare(factory)
        _run_worker(factory)
        application = _application(factory)
        response = http_client.post(
            "/api/session/select", json={"actor_id": "persona_data_steward"}
        )
        assert response.status_code == 200
        token = _csrf(http_client)
        response = http_client.post(
            "/api/session/select", json={"actor_id": "persona_permit_reviewer"}
        )
        assert response.status_code == 200
        posted = http_client.post(
            "/ui/actions/registry.automation.undo",
            data={
                "csrf_token": token,
                "application_id": application.id,
                "reason": UNDO_REASON,
                "next": "/steward/automation",
            },
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        assert posted.status_code == 403, posted.text
        with transaction(factory) as session:
            link = session.get(registry.Crosswalk, application.crosswalk_id)
            assert link is not None
            assert link.link_status == "approved"
    finally:
        factory.dispose()
