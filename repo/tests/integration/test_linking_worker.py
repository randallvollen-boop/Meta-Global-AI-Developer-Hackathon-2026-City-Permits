"""The durable linking work and the bounded worker that processes it.

The first part of the module covers the enqueue: an accepted source version
queues the work once, and the policy of the City decides whether it is queued
at all.  The second part covers the worker: it takes a job by a single
statement, it records the evidence of its decision, it retries a job that
stops for a technical reason, it returns the job a dead worker left behind
and it never applies a link on its own.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.agents import linking
from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.core.errors import ConflictError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.ingestion.schemas import IngestCommand, SourceRecordCommand
from acme_city.ingestion.service import IngestionService
from acme_city.persistence.models import audit, change, registry, registry_automation, source
from acme_city.registry import automation
from acme_city.registry.automation import enqueue_accepted_snapshot
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

PAYLOAD = {
    "party_ref": "party_applicant_1",
    "display_name": "Tamsin Aldous",
    "contact_email": "t.aldous+autolink@example.invalid",
    "contact_phone": "+1-555-0141",
    "preferred_contact": "email",
}

@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'linking-worker.db'}",
            "ACME_SECRET_KEY": "linking-worker-test-secret",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(DemoEnvironment(
                id="demo_environment_local",
                environment_id=ENVIRONMENT_ID,
                fictional_demo=True,
                fixture_version=bundle.fixture_version,
                label="local fictional demonstration",
            ))
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    finally:
        factory.dispose()
    return settings


def test_accepted_version_enqueues_once_when_policy_is_active(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            session.add(registry_automation.RegistryAutomationPolicy(
                id="policy_active_1",
                version=1,
                mode="active",
                status="active",
                matcher_version="registry-candidates-v1",
                thresholds={},
                source_scopes=["applicant_profiles"],
                reason="exercise durable enqueue",
                recorded_by_actor_id="persona_data_steward",
                activated_at=datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
            ))
        intake = IngestCommand(
            source_system_id="permitting",
            dataset_key="applicant_profiles",
            records=[SourceRecordCommand(
                source_record_id="PER-AP-0001",
                source_record_version="4",
                payload=PAYLOAD,
                source_updated_at=datetime(2026, 10, 29, 12, 1, tzinfo=UTC),
            )],
        )
        actor = ActorContext(actor_id="persona_data_steward", role_ids=frozenset())
        with transaction(factory) as session:
            service = IngestionService(session, registry_automation_mode="active")
            first = service.ingest(intake, actor)
            assert first.accepted == 1
        with transaction(factory) as session:
            service = IngestionService(session, registry_automation_mode="active")
            repeated = service.ingest(intake, actor)
            assert repeated.unchanged == 1
            jobs = session.execute(
                select(registry_automation.RegistryAutomationJob)
            ).scalars().all()
            assert len(jobs) == 1
            assert jobs[0].target_family == "owner_party"
            assert jobs[0].status == "pending"
            assert jobs[0].policy_id == "policy_active_1"
            snapshot = session.get(source.SourceSnapshot, jobs[0].source_snapshot_id)
            assert snapshot is not None
            duplicate_one = enqueue_accepted_snapshot(
                session, snapshot, dataset_key="applicant_profiles", automation_mode="active"
            )
            duplicate_two = enqueue_accepted_snapshot(
                session, snapshot, dataset_key="applicant_profiles", automation_mode="active"
            )
            assert duplicate_one is not None
            assert duplicate_two is not None
            assert duplicate_one.id == duplicate_two.id == jobs[0].id
            persisted = session.execute(
                select(registry_automation.RegistryAutomationJob)
            ).scalars().all()
            assert len(persisted) == 1
    finally:
        factory.dispose()



@pytest.mark.parametrize(
    ("policy_mode", "source_scopes"),
    [
        ("paused", ["applicant_profiles"]),
        ("active", ["contractor_register"]),
    ],
)
def test_policy_mode_and_source_scope_gate_enqueue(
    seeded: Settings, policy_mode: str, source_scopes: list[str]
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            session.add(registry_automation.RegistryAutomationPolicy(
                id=f"policy_gate_{policy_mode}",
                version=1,
                mode=policy_mode,
                status="active",
                matcher_version="registry-candidates-v1",
                thresholds={},
                source_scopes=source_scopes,
                reason="exercise policy enqueue gates",
                recorded_by_actor_id="persona_data_steward",
                activated_at=datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
            ))
        intake = IngestCommand(
            source_system_id="permitting",
            dataset_key="applicant_profiles",
            records=[SourceRecordCommand(
                source_record_id="PER-AP-0001",
                source_record_version="4",
                payload=PAYLOAD,
                source_updated_at=datetime(2026, 10, 29, 12, 1, tzinfo=UTC),
            )],
        )
        actor = ActorContext(actor_id="persona_data_steward", role_ids=frozenset())
        with transaction(factory) as session:
            result = IngestionService(
                session, registry_automation_mode="active"
            ).ingest(intake, actor)
            assert result.accepted == 1
            assert session.execute(
                select(registry_automation.RegistryAutomationJob)
            ).scalars().all() == []
    finally:
        factory.dispose()


# --------------------------------------------------------------- the worker


def _add_policy(
    factory: SessionFactory,
    *,
    policy_id: str = "policy_worker_1",
    mode: str = "active",
    source_scopes: list[str] | None = None,
) -> None:
    """Record an active policy so the ingestion queues the linking work."""
    with transaction(factory) as session:
        session.add(
            registry_automation.RegistryAutomationPolicy(
                id=policy_id,
                version=1,
                mode=mode,
                status="active",
                matcher_version="registry-candidates-v1",
                thresholds={},
                source_scopes=source_scopes or ["applicant_profiles"],
                reason="exercise the linking worker",
                recorded_by_actor_id="persona_data_steward",
                activated_at=datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
            )
        )


def _ingest(
    factory: SessionFactory,
    *,
    source_record_id: str = "PER-AP-0001",
    source_record_version: str = "4",
) -> None:
    """Accept a source version, which queues the linking work."""
    intake = IngestCommand(
        source_system_id="permitting",
        dataset_key="applicant_profiles",
        records=[
            SourceRecordCommand(
                source_record_id=source_record_id,
                source_record_version=source_record_version,
                payload=PAYLOAD,
                source_updated_at=datetime(2026, 10, 29, 12, 1, tzinfo=UTC),
            )
        ],
    )
    actor = ActorContext(actor_id="persona_data_steward", role_ids=frozenset())
    with transaction(factory) as session:
        service = IngestionService(session, registry_automation_mode="active")
        assert service.ingest(intake, actor).accepted == 1


def _jobs(factory: SessionFactory) -> list[registry_automation.RegistryAutomationJob]:
    """Return the linking jobs of the database, oldest first."""
    with transaction(factory) as session:
        rows = session.execute(
            select(registry_automation.RegistryAutomationJob).order_by(
                registry_automation.RegistryAutomationJob.created_at,
                registry_automation.RegistryAutomationJob.id,
            )
        ).scalars().all()
        return list(rows)


def test_the_worker_records_the_evidence_of_its_decision(
    seeded: Settings,
) -> None:
    """The worker takes a job and records the score, the scale and the evidence."""
    factory = SessionFactory(seeded.database_url)
    try:
        _add_policy(factory)
        _ingest(factory)
        jobs = _jobs(factory)
        assert len(jobs) == 1
        with transaction(factory) as session:
            report = linking.run_once(session)
        assert len(report.processed) == 1
        outcome = report.processed[0]
        assert outcome.job_id == jobs[0].id
        assert outcome.status == "completed"
        assert outcome.attempts == 1
        assert outcome.entity_id == "party_applicant_1"
        assert outcome.score == 0.70

        with transaction(factory) as session:
            job = session.get(registry_automation.RegistryAutomationJob, jobs[0].id)
            assert job is not None
            assert job.status == "completed"
            assert job.attempts == 1
            evaluations = session.execute(
                select(registry_automation.RegistryAutomationEvaluation)
            ).scalars().all()
            assert len(evaluations) == 1
            evaluation = evaluations[0]
            assert evaluation.target_entity_id == "party_applicant_1"
            assert evaluation.score == 0.70
            assert evaluation.score_scale == linking.SCORE_SCALE
            assert evaluation.decision in {"suggest", "auto_apply"}
            assert evaluation.evidence["supporting"]
            assert evaluation.evidence["compared_fields"]
            assert evaluation.evidence["reasons"]
    finally:
        factory.dispose()


def test_the_worker_never_applies_a_link(seeded: Settings) -> None:
    """The worker records a decision; a person applies the link."""
    factory = SessionFactory(seeded.database_url)
    try:
        _add_policy(factory)
        _ingest(factory)
        with transaction(factory) as session:
            linking.run_once(session)
        with transaction(factory) as session:
            links = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "PER-AP-0001"
                )
            ).scalars().all()
            assert links == []
            applications = session.execute(
                select(registry_automation.RegistryAutomationApplication)
            ).scalars().all()
            assert applications == []
    finally:
        factory.dispose()


def test_two_workers_never_take_the_same_job(seeded: Settings) -> None:
    """The claim is a single statement, so only one worker wins the job."""
    factory = SessionFactory(seeded.database_url)
    try:
        _add_policy(factory)
        _ingest(factory)
        job = _jobs(factory)[0]
        with transaction(factory) as session:
            first = linking.claim(session, job.id)
            second = linking.claim(session, job.id)
        assert first is not None
        assert first.status == "running"
        assert first.attempts == 1
        assert second is None
    finally:
        factory.dispose()


def test_the_finish_of_an_earlier_attempt_is_refused(seeded: Settings) -> None:
    """Only the worker that holds the attempt may finish the job."""
    factory = SessionFactory(seeded.database_url)
    try:
        _add_policy(factory)
        _ingest(factory)
        job = _jobs(factory)[0]
        with transaction(factory) as session:
            claimed = linking.claim(session, job.id)
            assert claimed is not None
            late = linking.finish(session, job.id, claimed.attempts + 1, "completed")
            held = linking.finish(session, job.id, claimed.attempts, "completed")
        assert late is None
        assert held is not None
        assert held.status == "completed"
    finally:
        factory.dispose()


def test_a_job_that_stops_is_tried_again_and_then_waits_for_a_person(
    seeded: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A technical failure is retried; the third attempt waits for a person."""
    factory = SessionFactory(seeded.database_url)
    try:
        _add_policy(factory)
        _ingest(factory)
        job = _jobs(factory)[0]

        def stop(*args: object, **kwargs: object) -> None:
            raise RuntimeError("the comparison stopped")

        monkeypatch.setattr(linking, "process_job", stop)
        for expected in (1, 2):
            with transaction(factory) as session:
                report = linking.run_once(session)
            assert report.processed[0].status == "failed"
            with transaction(factory) as session:
                row = session.get(registry_automation.RegistryAutomationJob, job.id)
                assert row is not None
                assert row.attempts == expected
                assert row.status == "failed"

        with transaction(factory) as session:
            report = linking.run_once(session)
        assert report.processed[0].status == "needs_review"
        with transaction(factory) as session:
            row = session.get(registry_automation.RegistryAutomationJob, job.id)
            assert row is not None
            assert row.attempts == linking.MAX_ATTEMPTS
            assert row.status == "needs_review"

        # A job that used up its attempts is never tried again.
        with transaction(factory) as session:
            report = linking.run_once(session)
        assert report.processed == ()
        with transaction(factory) as session:
            row = session.get(registry_automation.RegistryAutomationJob, job.id)
            assert row is not None
            assert row.attempts == linking.MAX_ATTEMPTS
    finally:
        factory.dispose()


def test_the_worker_returns_the_job_a_dead_worker_left_running(
    seeded: Settings,
) -> None:
    """A job that was running before the worker started is worked again."""
    factory = SessionFactory(seeded.database_url)
    try:
        _add_policy(factory)
        _ingest(factory)
        job = _jobs(factory)[0]
        with transaction(factory) as session:
            row = session.get(registry_automation.RegistryAutomationJob, job.id)
            assert row is not None
            row.status = "running"
            row.attempts = 1
            row.claimed_at = datetime(2026, 10, 29, 11, 0, tzinfo=UTC)
        with transaction(factory) as session:
            report = linking.run_once(
                session, started_at=datetime(2026, 10, 29, 12, 30, tzinfo=UTC)
            )
        assert report.recovered == 1
        assert len(report.processed) == 1
        assert report.processed[0].attempts == 2
    finally:
        factory.dispose()


def test_one_cycle_is_bounded(seeded: Settings) -> None:
    """A cycle takes at most the number of jobs it was given."""
    factory = SessionFactory(seeded.database_url)
    try:
        _add_policy(factory)
        _ingest(factory, source_record_id="PER-AP-0001", source_record_version="4")
        _ingest(factory, source_record_id="PER-AP-0002", source_record_version="4")
        assert len(_jobs(factory)) == 2
        with transaction(factory) as session:
            report = linking.run_once(session, limit=1)
        assert len(report.processed) == 1
        statuses = [job.status for job in _jobs(factory)]
        assert sorted(statuses) == ["completed", "pending"]
    finally:
        factory.dispose()


def test_the_worker_does_nothing_when_the_policy_is_paused(
    seeded: Settings,
) -> None:
    """A paused policy leaves the waiting work alone."""
    factory = SessionFactory(seeded.database_url)
    try:
        _add_policy(factory)
        _ingest(factory)
        with transaction(factory) as session:
            policy = session.get(
                registry_automation.RegistryAutomationPolicy, "policy_worker_1"
            )
            assert policy is not None
            policy.mode = "paused"
        with transaction(factory) as session:
            report = linking.run_once(session)
        assert report.processed == ()
        assert _jobs(factory)[0].status == "pending"

        # A policy that is withdrawn leaves the job waiting for a person.
        with transaction(factory) as session:
            policy = session.get(
                registry_automation.RegistryAutomationPolicy, "policy_worker_1"
            )
            assert policy is not None
            policy.mode = "active"
            policy.status = "superseded"
        with transaction(factory) as session:
            report = linking.run_once(session)
        assert report.processed == ()
        assert _jobs(factory)[0].status == "pending"
    finally:
        factory.dispose()


def test_the_worker_only_covers_the_datasets_of_the_policy(
    seeded: Settings,
) -> None:
    """A record outside the scope of the policy is never queued."""
    factory = SessionFactory(seeded.database_url)
    try:
        _add_policy(factory, source_scopes=["contractor_register"])
        _ingest(factory)
        assert len(_jobs(factory)) == 0
    finally:
        factory.dispose()


# ----------------------------------------------------------- the application


class _Rollback(Exception):
    """Raised inside a transaction to undo everything it wrote."""


def _eligible_evaluation(
    factory: SessionFactory,
    *,
    entity_id: str = "party_applicant_1",
    decision: str = "auto_apply",
) -> str:
    """Record an evaluation of one candidate and return its identifier."""
    job = _jobs(factory)[0]
    with transaction(factory) as session:
        snapshot = session.get(source.SourceSnapshot, job.source_snapshot_id)
        assert snapshot is not None
        evaluation = registry_automation.RegistryAutomationEvaluation(
            id="autoeval_test",
            job_id=job.id,
            source_snapshot_id=snapshot.source_snapshot_id,
            policy_id="policy_worker_1",
            target_family="owner_party",
            target_entity_id=entity_id,
            score=0.70,
            score_scale=linking.SCORE_SCALE,
            decision=decision,
            evidence={
                "reasons": ["eligible"],
                "failed_checks": [],
                "compared_fields": ["party_ref"],
                "supporting": [],
                "conflicting": [],
                "matcher_version": "registry-candidates-v1",
            },
        )
        session.add(evaluation)
    return evaluation.id


def test_the_application_writes_the_link_the_audit_and_the_review_task(
    seeded: Settings,
) -> None:
    """One application writes the link, the trail and the review item together."""
    factory = SessionFactory(seeded.database_url)
    try:
        _add_policy(factory)
        _ingest(factory)
        evaluation_id = _eligible_evaluation(factory)
        with transaction(factory) as session:
            evaluation = session.get(
                registry_automation.RegistryAutomationEvaluation, evaluation_id
            )
            assert evaluation is not None
            policy = session.get(
                registry_automation.RegistryAutomationPolicy, "policy_worker_1"
            )
            assert policy is not None
            application = automation.apply_evaluation(
                session,
                evaluation=evaluation,
                policy=policy,
                actor=linking.service_actor(),
            )
            application_id = application.id

        with transaction(factory) as session:
            links = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "PER-AP-0001"
                )
            ).scalars().all()
            assert len(links) == 1
            link = links[0]
            assert link.link_status == "approved"
            assert link.entity_id == "party_applicant_1"
            assert link.decision_actor_id == linking.LINKING_ACTOR_ID
            assert link.decided_at is not None

            applications = session.execute(
                select(registry_automation.RegistryAutomationApplication)
            ).scalars().all()
            assert len(applications) == 1
            recorded = applications[0]
            assert recorded.id == application_id
            assert recorded.crosswalk_id == link.id
            assert recorded.status == "applied"
            assert recorded.applied_by_actor_id == linking.LINKING_ACTOR_ID
            assert recorded.before_state["link_status"] == "none"
            assert recorded.after_state["entity_id"] == "party_applicant_1"
            assert recorded.after_state["link_status"] == "approved"

            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == automation.APPLY_ACTION
                )
            ).scalars().all()
            assert len(events) == 1
            event = events[0]
            assert event.actor_id == linking.LINKING_ACTOR_ID
            assert event.metadata_json["authorized_by_actor_id"] == "persona_data_steward"
            assert event.metadata_json["policy_version"] == 1
            assert link.id in (event.references or [])

            tasks = session.execute(
                select(change.ReviewTask).where(
                    change.ReviewTask.task_type == automation.REVIEW_TASK_TYPE
                )
            ).scalars().all()
            assert len(tasks) == 1
            assert tasks[0].target_id == link.id
            assert tasks[0].assignee_actor_id == "persona_data_steward"
            assert tasks[0].status == "open"
    finally:
        factory.dispose()


def test_the_application_is_written_in_one_transaction(seeded: Settings) -> None:
    """Nothing of an undone application is left behind."""
    factory = SessionFactory(seeded.database_url)
    try:
        _add_policy(factory)
        _ingest(factory)
        evaluation_id = _eligible_evaluation(factory)
        with pytest.raises(_Rollback):
            with transaction(factory) as session:
                evaluation = session.get(
                    registry_automation.RegistryAutomationEvaluation, evaluation_id
                )
                assert evaluation is not None
                policy = session.get(
                    registry_automation.RegistryAutomationPolicy, "policy_worker_1"
                )
                assert policy is not None
                automation.apply_evaluation(
                    session,
                    evaluation=evaluation,
                    policy=policy,
                    actor=linking.service_actor(),
                )
                raise _Rollback()

        with transaction(factory) as session:
            links = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "PER-AP-0001"
                )
            ).scalars().all()
            assert links == []
            applications = session.execute(
                select(registry_automation.RegistryAutomationApplication)
            ).scalars().all()
            assert applications == []
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == automation.APPLY_ACTION
                )
            ).scalars().all()
            assert events == []
            tasks = session.execute(
                select(change.ReviewTask).where(
                    change.ReviewTask.task_type == automation.REVIEW_TASK_TYPE
                )
            ).scalars().all()
            assert tasks == []
    finally:
        factory.dispose()


def test_an_approved_link_of_another_entity_is_never_replaced(
    seeded: Settings,
) -> None:
    """A decision of a person is not replaced by the automation."""
    factory = SessionFactory(seeded.database_url)
    try:
        _add_policy(factory)
        _ingest(factory)
        evaluation_id = _eligible_evaluation(factory)
        with transaction(factory) as session:
            session.add(
                registry.Crosswalk(
                    id="crosswalk_manual",
                    entity_id="party_applicant_2",
                    entity_type="party",
                    source_system_id="permitting",
                    source_dataset_key="applicant_profiles",
                    source_record_id="PER-AP-0001",
                    link_status="approved",
                    decision="the steward decided this link",
                    decision_actor_id="persona_data_steward",
                    decided_at=datetime(2026, 10, 29, 11, 0, tzinfo=UTC),
                    expected_version=None,
                    valid_from=datetime(2026, 10, 29, 11, 0, tzinfo=UTC),
                    valid_to=None,
                    superseded_by_crosswalk_id=None,
                    scenario_id=None,
                )
            )
        with pytest.raises(ConflictError):
            with transaction(factory) as session:
                evaluation = session.get(
                    registry_automation.RegistryAutomationEvaluation, evaluation_id
                )
                assert evaluation is not None
                policy = session.get(
                    registry_automation.RegistryAutomationPolicy, "policy_worker_1"
                )
                assert policy is not None
                automation.apply_evaluation(
                    session,
                    evaluation=evaluation,
                    policy=policy,
                    actor=linking.service_actor(),
                )
        with transaction(factory) as session:
            link = session.get(registry.Crosswalk, "crosswalk_manual")
            assert link is not None
            assert link.entity_id == "party_applicant_2"
            assert link.link_status == "approved"
            assert link.decision == "the steward decided this link"
    finally:
        factory.dispose()


def test_the_worker_suggests_until_the_family_can_be_taken_back(
    seeded: Settings,
) -> None:
    """A family without a tested reversal is never applied on its own."""
    factory = SessionFactory(seeded.database_url)
    try:
        _add_policy(factory)
        _ingest(factory)
        with transaction(factory) as session:
            report = linking.run_once(session)
        assert report.processed[0].decision == "suggest"
        with transaction(factory) as session:
            evaluation = session.execute(
                select(registry_automation.RegistryAutomationEvaluation)
            ).scalar_one()
            assert evaluation.decision == "suggest"
            assert "undo_supported" in evaluation.evidence["failed_checks"]
            applications = session.execute(
                select(registry_automation.RegistryAutomationApplication)
            ).scalars().all()
            assert applications == []
    finally:
        factory.dispose()
