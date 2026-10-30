"""The bounded worker that processes the durable registry linking work.

The worker takes the work the registry automation queued, compares the source
record with the canonical entities it may belong to, and records what it
decided.  It follows the runtime contract of the agents: one status column, an
attempt count and no lease.  A job is taken by a single statement, so two
workers never commit the same job, and the finish names the attempt it ends,
so a late finish of an earlier attempt is refused.

The worker is bounded.  One cycle takes at most a fixed number of jobs and
stops there.  A job that stops for a technical reason is tried again until it
used up its attempts, and a job that used them up waits for a person.  The
worker never calls the model provider: the comparison is the built in
deterministic logic of the City.
"""
# REQUIRES: MDM-02, MDM-03, SEC-01
# The worker claims one job at a time, records the evidence of its decision
# and never applies a link on its own.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.ids import new_id
from acme_city.persistence.models import governance, registry, registry_automation, source
from acme_city.registry import automation, candidates
from acme_city.registry.automation_policy import (
    UNDO_SUPPORTED_FAMILIES,
    PolicyDecision,
    SafetyChecks,
    Thresholds,
    evaluate_link,
    thresholds_for,
)

#: The actor the worker records its work under.  It is a service identity: it
#: is never offered a session and it holds no grant of a person.
LINKING_ACTOR_ID = "service_linking_agent"

#: The most jobs one cycle takes.
MAX_JOBS_PER_CYCLE = 20

#: The most attempts one job may have: the first try and two retries.  A job
#: that was tried that often waits for a person.
MAX_ATTEMPTS = 3

#: The name of the score scale of the registry candidate score.  The score is
#: an ordering of the candidates, not a probability.
SCORE_SCALE = "registry_candidate_0_1"

#: The most candidates one job records.  The candidates are ordered by their
#: score, so the ones that matter are the first ones.
MAX_EVALUATIONS_PER_JOB = 10

#: The permission the service identity needs to compare a source record.
PROPOSE_ACTION = "registry.crosswalk.propose"

#: The evidence that names a party on its own.
EXACT_REFERENCE_METHODS: frozenset[str] = frozenset({"source_reference_exact"})

#: The evidence that corroborates an exact identifier.
CORROBORATING_METHODS: frozenset[str] = frozenset(
    {
        "name_normalized_exact",
        "alias_normalized_exact",
        "credential_exact",
        "address_exact",
    }
)

#: The exact identifier every family needs before a link may be applied.
FAMILY_EXACT_METHODS: dict[str, frozenset[str]] = {
    "owner_party": EXACT_REFERENCE_METHODS,
    "contractor_party": frozenset({"credential_exact"}),
    "parcel": frozenset({"parcel_identifier_exact"}),
    "address": frozenset({"address_identifier_exact"}),
}

#: The payload fields every family needs before a link may be applied.
FAMILY_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "owner_party": ("party_ref", "holder_ref"),
    "contractor_party": ("license_number", "registration_number"),
    "parcel": ("parcel_number", "submitted_parcel"),
    "address": ("address_id", "address_ref"),
}

#: The entity type every family compares against.
FAMILY_ENTITY_TYPES: dict[str, str] = {
    "owner_party": "party",
    "contractor_party": "party",
    "parcel": "parcel",
    "address": "address",
}

#: The states a job may hold.  They mirror the queue of the agents.
JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class JobOutcome:
    """What one job of the worker decided."""

    job_id: str
    status: str
    decision: str
    entity_id: str | None = None
    score: float | None = None
    attempts: int = 0
    note: str = ""


@dataclass(frozen=True)
class WorkerReport:
    """What one cycle of the worker did."""

    recovered: int = 0
    reopened: int = 0
    processed: tuple[JobOutcome, ...] = ()


def service_actor() -> ActorContext:
    """Return the actor context of the linking service identity."""
    return ActorContext(actor_id=LINKING_ACTOR_ID, role_ids=frozenset())


# --------------------------------------------------------------------- queue


def pending_jobs(session: Session, *, limit: int) -> list[registry_automation.RegistryAutomationJob]:
    """Return the waiting jobs, oldest first, at most ``limit`` of them."""
    rows = session.execute(
        select(registry_automation.RegistryAutomationJob)
        .where(registry_automation.RegistryAutomationJob.status == JOB_PENDING)
        .order_by(
            registry_automation.RegistryAutomationJob.available_at,
            registry_automation.RegistryAutomationJob.created_at,
            registry_automation.RegistryAutomationJob.id,
        )
        .limit(max(0, limit))
    ).scalars().all()
    return list(rows)


def claim(
    session: Session,
    job_id: str,
    *,
    now: datetime | None = None,
) -> registry_automation.RegistryAutomationJob | None:
    """Take one job.

    The statement moves the row from ``pending`` to ``running`` and counts the
    attempt.  Two workers that ask for the same job at the same time cannot
    both win it: the second statement changes no row and the claim is
    refused.
    """
    result = session.execute(
        update(registry_automation.RegistryAutomationJob)
        .where(
            registry_automation.RegistryAutomationJob.id == job_id,
            registry_automation.RegistryAutomationJob.status == JOB_PENDING,
        )
        .values(
            status=JOB_RUNNING,
            attempts=registry_automation.RegistryAutomationJob.attempts + 1,
            claimed_at=now or utc_now(),
            finished_at=None,
            last_error=None,
        )
    )
    if result.rowcount == 0:
        return None
    return session.get(registry_automation.RegistryAutomationJob, job_id, populate_existing=True)


def finish(
    session: Session,
    job_id: str,
    attempt: int,
    status: str,
    *,
    note: str | None = None,
    now: datetime | None = None,
) -> registry_automation.RegistryAutomationJob | None:
    """Record the outcome of one attempt of one job.

    Only the worker that holds the job may finish it: the row has to be
    ``running`` and its attempt count has to be the attempt the worker holds.
    The late finish of an attempt that already ended is refused.
    """
    if status not in (JOB_COMPLETED, JOB_FAILED, JOB_NEEDS_REVIEW):
        raise ValueError(f"not a finished state: {status!r}")
    result = session.execute(
        update(registry_automation.RegistryAutomationJob)
        .where(
            registry_automation.RegistryAutomationJob.id == job_id,
            registry_automation.RegistryAutomationJob.status == JOB_RUNNING,
            registry_automation.RegistryAutomationJob.attempts == attempt,
        )
        .values(
            status=status,
            finished_at=now or utc_now(),
            last_error=note if status in (JOB_FAILED, JOB_NEEDS_REVIEW) else None,
        )
    )
    if result.rowcount == 0:
        return None
    return session.get(registry_automation.RegistryAutomationJob, job_id, populate_existing=True)


def recover_running(session: Session, before: datetime) -> int:
    """Return the jobs that were running before this moment to the waiting state.

    A process that ended while a job was being worked leaves its row running.
    The next worker returns that job to the waiting state, so the record is
    worked again instead of waiting for ever.  Only the jobs that were claimed
    before the worker started are returned: the jobs of the worker that is
    running now are never touched.

    Returns:
        The number of jobs that were returned to the waiting state.
    """
    result = session.execute(
        update(registry_automation.RegistryAutomationJob)
        .where(
            registry_automation.RegistryAutomationJob.status == JOB_RUNNING,
            registry_automation.RegistryAutomationJob.claimed_at.is_not(None),
            registry_automation.RegistryAutomationJob.claimed_at < before,
        )
        .values(
            status=JOB_PENDING,
            claimed_at=None,
            finished_at=None,
            last_error="the attempt was interrupted; the job waits for another attempt",
        )
    )
    return int(result.rowcount or 0)


def reopen_failed(session: Session) -> int:
    """Return the failed jobs that may be tried again to the waiting state.

    Only a technical failure is tried again, and only while the job has
    attempts left: a job that was tried three times stays failed and waits
    for a person.

    Returns:
        The number of jobs that were returned to the waiting state.
    """
    result = session.execute(
        update(registry_automation.RegistryAutomationJob)
        .where(
            registry_automation.RegistryAutomationJob.status == JOB_FAILED,
            registry_automation.RegistryAutomationJob.attempts < MAX_ATTEMPTS,
        )
        .values(
            status=JOB_PENDING,
            claimed_at=None,
            finished_at=None,
            last_error=None,
        )
    )
    return int(result.rowcount or 0)


# ------------------------------------------------------------------- the work


def _contract(session: Session, snapshot: source.SourceSnapshot) -> governance.SourceContract | None:
    """Return the registered contract of the dataset of a snapshot."""
    return session.execute(
        select(governance.SourceContract).where(
            governance.SourceContract.source_system_id == snapshot.source_system_id,
            governance.SourceContract.dataset_key == snapshot.source_dataset_id,
        )
    ).scalar_one_or_none()


def _crosswalk_rows(
    session: Session, snapshot: source.SourceSnapshot
) -> list[registry.Crosswalk]:
    """Return every link of a source record, oldest first."""
    return list(
        session.execute(
            select(registry.Crosswalk)
            .where(
                registry.Crosswalk.source_system_id == snapshot.source_system_id,
                registry.Crosswalk.source_record_id == snapshot.source_record_id,
            )
            .order_by(registry.Crosswalk.created_at, registry.Crosswalk.id)
        ).scalars().all()
    )


def _current_snapshot(
    session: Session, snapshot: source.SourceSnapshot
) -> source.SourceSnapshot | None:
    """Return the accepted snapshot of the record that is current now."""
    rows = session.execute(
        select(source.SourceSnapshot).where(
            source.SourceSnapshot.source_system_id == snapshot.source_system_id,
            source.SourceSnapshot.source_dataset_id == snapshot.source_dataset_id,
            source.SourceSnapshot.source_record_id == snapshot.source_record_id,
            source.SourceSnapshot.record_status == "accepted",
        )
    ).scalars().all()
    if not rows:
        return None

    def sort_key(row: source.SourceSnapshot) -> tuple[int, int, datetime]:
        numeric = row.source_record_version or ""
        return (
            int(numeric) if numeric.isdigit() else -1,
            1 if row.source_updated_at is not None else 0,
            row.source_updated_at or row.ingested_at,
        )

    return max(rows, key=sort_key)


def _target_exists(
    session: Session, entity_id: str, entity_type: str
) -> bool:
    """Return whether the canonical entity exists with the expected type."""
    entity = session.execute(
        select(registry.CanonicalEntity).where(
            registry.CanonicalEntity.entity_id == entity_id
        )
    ).scalar_one_or_none()
    if entity is None:
        return False
    return entity.entity_type == entity_type


def _required_fields_present(family: str, payload: dict[str, Any]) -> bool:
    """Return whether the payload carries the fields the family needs."""
    fields = FAMILY_REQUIRED_FIELDS.get(family, ())
    return any(payload.get(name) for name in fields)


def _exact_identifier_present(family: str, candidate: candidates.Candidate) -> bool:
    """Return whether the candidate carries the exact identifier of the family."""
    methods = {item.method for item in candidate.supporting}
    return bool(methods & FAMILY_EXACT_METHODS.get(family, frozenset()))


def _corroborated(family: str, candidate: candidates.Candidate) -> bool:
    """Return whether the exact identifier is corroborated by other evidence."""
    methods = {item.method for item in candidate.supporting}
    return bool(methods & CORROBORATING_METHODS)


def safety_checks(
    session: Session,
    *,
    snapshot: source.SourceSnapshot,
    family: str,
    candidate: candidates.Candidate,
    candidate_count: int,
) -> SafetyChecks:
    """Return the safety checks of one candidate.

    The checks are the facts a threshold may never override: the source
    version has to be current, the target has to exist, the identity has to
    carry an exact identifier and a corroborating fact, and no decision of a
    person may be replaced.  A family whose links cannot be reversed is only
    ever suggested.
    """
    payload = dict(snapshot.raw_payload or {})
    contract = _contract(session, snapshot)
    current = _current_snapshot(session, snapshot)
    rows = _crosswalk_rows(session, snapshot)
    approved = [row for row in rows if row.link_status == "approved"]
    rejected = [row for row in rows if row.link_status == "rejected"]
    entity_type = FAMILY_ENTITY_TYPES.get(family, "party")
    actor = service_actor()
    resolver = PermissionResolver(session)
    domain_id = contract.domain_id if contract is not None else None
    permitted = resolver.allows(
        actor,
        PROPOSE_ACTION,
        ResourceContext(
            domain_id=domain_id,
            record_type="source_record",
            record_ids=(snapshot.source_record_id,),
        ),
    )
    return SafetyChecks(
        source_accepted_current=(
            snapshot.record_status == "accepted"
            and current is not None
            and current.source_snapshot_id == snapshot.source_snapshot_id
        ),
        source_contract_eligible=(
            contract is not None and contract.registration_state == "complete"
        ),
        target_exists_with_correct_type=_target_exists(
            session, candidate.entity_id, entity_type
        ),
        identifier_namespace_known=family in FAMILY_ENTITY_TYPES,
        required_identity_fields_present=_required_fields_present(family, payload),
        no_identity_conflict=not candidate.conflicting,
        no_protected_manual_decision=not approved and not rejected,
        comparison_current=current is not None
        and current.source_snapshot_id == snapshot.source_snapshot_id,
        no_active_link_replacement=not any(
            row.entity_id != candidate.entity_id for row in approved
        ),
        undo_supported=family in UNDO_SUPPORTED_FAMILIES,
        permissions_granted=permitted,
        unique_target=candidate_count == 1,
        corroborating_identity_evidence=(
            _exact_identifier_present(family, candidate) and _corroborated(family, candidate)
        ),
    )


def _thresholds(
    policy: registry_automation.RegistryAutomationPolicy, family: str
) -> Thresholds:
    """Return the thresholds of one family, from the policy or the defaults."""
    stored = (policy.thresholds or {}).get(family)
    return thresholds_for(family, stored)


def _record_evaluation(
    session: Session,
    *,
    job: registry_automation.RegistryAutomationJob,
    snapshot: source.SourceSnapshot,
    policy: registry_automation.RegistryAutomationPolicy,
    family: str,
    candidate: candidates.Candidate,
    decision: PolicyDecision,
    score: float,
    reasons: tuple[str, ...],
    checks: SafetyChecks,
) -> registry_automation.RegistryAutomationEvaluation:
    """Record the evidence of one candidate as an immutable evaluation."""
    evaluation = registry_automation.RegistryAutomationEvaluation(
        id=new_id("autoeval"),
        job_id=job.id,
        source_snapshot_id=snapshot.source_snapshot_id,
        policy_id=policy.id,
        target_family=family,
        target_entity_id=candidate.entity_id,
        score=score,
        score_scale=SCORE_SCALE,
        decision=decision.value,
        evidence={
            "reasons": list(reasons),
            "failed_checks": list(checks.failures()),
            "compared_fields": sorted(
                {item.field for item in candidate.supporting}
                | {item.field for item in candidate.conflicting}
            ),
            "supporting": [item.to_dict() for item in candidate.supporting],
            "conflicting": [item.to_dict() for item in candidate.conflicting],
            "matcher_version": job.matcher_version,
        },
    )
    session.add(evaluation)
    session.flush()
    return evaluation


def process_job(
    session: Session,
    job: registry_automation.RegistryAutomationJob,
    *,
    now: datetime | None = None,
) -> JobOutcome:
    """Process one job and return what it decided.

    The job is checked against the policy that is active right now, the
    source version is checked against the version that is current, and every
    candidate is compared and recorded with its evidence.  A job that needs a
    person says so; a job that is done says so as well.
    """
    moment = now or utc_now()
    policy = automation.active_policy(session)
    if policy is None:
        return JobOutcome(
            job_id=job.id,
            status=JOB_NEEDS_REVIEW,
            decision="",
            attempts=job.attempts,
            note="no policy is active, so the record waits for a person",
        )
    snapshot = session.get(source.SourceSnapshot, job.source_snapshot_id)
    if snapshot is None or snapshot.record_status != "accepted":
        return JobOutcome(
            job_id=job.id,
            status=JOB_NEEDS_REVIEW,
            decision="",
            attempts=job.attempts,
            note="the source record has no accepted version",
        )
    dataset_key = snapshot.source_dataset_id
    if dataset_key not in (policy.source_scopes or []):
        return JobOutcome(
            job_id=job.id,
            status=JOB_NEEDS_REVIEW,
            decision="",
            attempts=job.attempts,
            note="the active policy does not cover this source dataset",
        )

    family = job.target_family
    entity_type = FAMILY_ENTITY_TYPES.get(family, "party")
    candidate_set = candidates.generate_candidates(
        session,
        dict(snapshot.raw_payload or {}),
        entity_type,
        snapshot.source_snapshot_id,
    )
    thresholds = _thresholds(policy, family)
    best: tuple[
        candidates.Candidate,
        PolicyDecision,
        float,
        tuple[str, ...],
        registry_automation.RegistryAutomationEvaluation,
    ] | None = None
    for candidate in candidate_set.candidates[:MAX_EVALUATIONS_PER_JOB]:
        checks = safety_checks(
            session,
            snapshot=snapshot,
            family=family,
            candidate=candidate,
            candidate_count=len(candidate_set.candidates),
        )
        next_best = next(
            (
                other.score
                for other in candidate_set.candidates
                if other.entity_id != candidate.entity_id
            ),
            None,
        )
        evaluation = evaluate_link(
            target_family=family,
            score=candidate.score,
            checks=checks,
            next_best_score=next_best,
            thresholds=thresholds,
        )
        recorded = _record_evaluation(
            session,
            job=job,
            snapshot=snapshot,
            policy=policy,
            family=family,
            candidate=candidate,
            decision=evaluation.decision,
            score=candidate.score,
            reasons=evaluation.reasons,
            checks=checks,
        )
        if best is None or candidate.score > best[2]:
            best = (
                candidate,
                evaluation.decision,
                candidate.score,
                evaluation.reasons,
                recorded,
            )

    if best is None:
        return JobOutcome(
            job_id=job.id,
            status=JOB_COMPLETED,
            decision=PolicyDecision.IGNORE.value,
            attempts=job.attempts,
            note="no candidate was found for this record",
        )
    candidate, decision, score, reasons, recorded = best
    if decision is PolicyDecision.IGNORE:
        return JobOutcome(
            job_id=job.id,
            status=JOB_COMPLETED,
            decision=decision.value,
            entity_id=candidate.entity_id,
            score=score,
            attempts=job.attempts,
            note="the score is below the suggestion threshold",
        )
    if decision is PolicyDecision.SUGGEST:
        return JobOutcome(
            job_id=job.id,
            status=JOB_COMPLETED,
            decision=decision.value,
            entity_id=candidate.entity_id,
            score=score,
            attempts=job.attempts,
            note="a person decides: " + ", ".join(reasons),
        )
    if policy.mode != "active":
        return JobOutcome(
            job_id=job.id,
            status=JOB_COMPLETED,
            decision=PolicyDecision.SUGGEST.value,
            entity_id=candidate.entity_id,
            score=score,
            attempts=job.attempts,
            note="the policy records suggestions only, so a person decides",
        )
    application = automation.apply_evaluation(
        session,
        evaluation=recorded,
        policy=policy,
        actor=service_actor(),
        now=moment,
    )
    return JobOutcome(
        job_id=job.id,
        status=JOB_COMPLETED,
        decision=decision.value,
        entity_id=candidate.entity_id,
        score=score,
        attempts=job.attempts,
        note=f"the link was applied and waits for a review: {application.id}",
    )


def _work(
    session: Session,
    job: registry_automation.RegistryAutomationJob,
    *,
    now: datetime,
) -> JobOutcome:
    """Work one claimed job and finish it.

    A job that stops for a technical reason is left failed, so it is tried
    again.  A job that used up its attempts waits for a person instead.
    """
    try:
        outcome = process_job(session, job, now=now)
    except Exception as error:  # noqa: BLE001 - the failure is recorded
        note = f"the job failed: {error}"
        status = JOB_NEEDS_REVIEW if job.attempts >= MAX_ATTEMPTS else JOB_FAILED
        finish(session, job.id, job.attempts, status, note=note, now=now)
        return JobOutcome(
            job_id=job.id,
            status=status,
            decision="",
            attempts=job.attempts,
            note=note,
        )
    finish(session, job.id, job.attempts, outcome.status, note=outcome.note, now=now)
    return outcome


def run_once(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int = MAX_JOBS_PER_CYCLE,
    started_at: datetime | None = None,
) -> WorkerReport:
    """Process the waiting linking work once and report what happened.

    The cycle returns the jobs an earlier process left running to the waiting
    state, and then takes the waiting jobs one at a time.  A job is taken by a
    single statement, so two workers never commit the same job.  The cycle is
    bounded: it takes at most ``limit`` jobs and stops there.
    """
    moment = now or utc_now()
    horizon = started_at or moment
    recovered = recover_running(session, horizon)
    reopened = reopen_failed(session)
    policy = automation.active_policy(session)
    if policy is None or policy.mode == "paused":
        return WorkerReport(recovered=recovered, reopened=reopened, processed=())
    outcomes: list[JobOutcome] = []
    for job in pending_jobs(session, limit=limit):
        claimed = claim(session, job.id, now=moment)
        if claimed is None:
            continue
        outcomes.append(_work(session, claimed, now=moment))
    return WorkerReport(
        recovered=recovered, reopened=reopened, processed=tuple(outcomes)
    )


__all__ = [
    "CORROBORATING_METHODS",
    "EXACT_REFERENCE_METHODS",
    "FAMILY_ENTITY_TYPES",
    "FAMILY_EXACT_METHODS",
    "FAMILY_REQUIRED_FIELDS",
    "JOB_COMPLETED",
    "JOB_FAILED",
    "JOB_NEEDS_REVIEW",
    "JOB_PENDING",
    "JOB_RUNNING",
    "LINKING_ACTOR_ID",
    "MAX_ATTEMPTS",
    "MAX_EVALUATIONS_PER_JOB",
    "MAX_JOBS_PER_CYCLE",
    "PROPOSE_ACTION",
    "SCORE_SCALE",
    "JobOutcome",
    "WorkerReport",
    "claim",
    "finish",
    "pending_jobs",
    "process_job",
    "recover_running",
    "reopen_failed",
    "run_once",
    "safety_checks",
    "service_actor",
]
