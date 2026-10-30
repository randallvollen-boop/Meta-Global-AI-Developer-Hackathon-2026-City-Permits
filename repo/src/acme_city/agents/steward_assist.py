"""The steward assistant: the agent that prepares the work of the queue.

The assistant reads a task of the Data Steward's queue, gathers the evidence
the City already holds and proposes a decision, a confidence and the words the
steward reads.  It never decides: the steward accepts the recommendation,
changes it, ignores it or clears it, and the steward is the decider of record.

The assistant is a service identity, like the intake agent and the adjudication
agent.  It sleeps until the Agent Operator wakes it, and it works only when a
person with the ``agent.run.steward_assist`` grant asks it to: the Data
Steward presses **Prepare recommendations** on the queue or **Get
recommendation** on one task.  Nothing runs on a timer, nothing runs when a
new task arrives, and one press names at most twenty tasks.

Every press leaves a run trace in the same table as the runs of the other two
agents, so the run history of the operator shows what the assistant did, when
it did it and at whose request.
"""
# REQUIRES: PER-01, PER-04, SEC-01, UX-01
# The assistant proposes and the steward decides.  Every write that follows an
# accepted recommendation goes through the existing service of the task kind,
# with the steward as the decider and the recommendation recorded in the
# audit trail.

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.agents.control import AgentControlService
from acme_city.agents.runtime import BUILTIN_ENGINE
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import change, gis, registry, registry_automation
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.registry import steward_assist as recommenders

#: The service identity the assistant records its work under.  It is never
#: offered a session and it holds no grant of a person.
SERVICE_ACTOR_ID = recommenders.STEWARD_ASSIST_ACTOR_ID

#: The most tasks one press of the assistant may name.  A press prepares the
#: work of the queue in bounded steps, so a long queue never turns into one
#: unbounded run.
MAX_TASKS_PER_PRESS = 20

#: The agent key of the assistant in the run history and the awake state.
AGENT_KEY = agent_models.AGENT_STEWARD_ASSIST

#: The message of a recommendation that no longer matches the record it read.
STALE_MESSAGE = "This record changed; refresh the recommendation"

#: The message of a recommendation that is held for a person.
HELD_MESSAGE = (
    "this recommendation is held for a person; use the normal controls of the case"
)


@dataclass(frozen=True)
class Prepared:
    """What one press of the assistant prepared."""

    #: The recorded run of the press.
    run: agent_models.AgentRun
    #: The recommendations the press recorded.
    recommendations: tuple[StewardRecommendation, ...]
    #: The tasks the press could not prepare, with the reason.
    refused: tuple[tuple[str, str], ...]


def _service_actor(session: Session, actor_id: str = SERVICE_ACTOR_ID) -> ActorContext:
    """Return the server-resolved context of the service identity."""
    from acme_city.auth.permissions import PermissionResolver

    grants = PermissionResolver(session).grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        role_ids=frozenset(),
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record for grant in grants for record in grant.record_scope
        ),
    )


def recommendation_for(
    session: Session, task_kind: str, task_id: str
) -> StewardRecommendation | None:
    """Return the recommendation the assistant prepared for one task.

    A task holds one recommendation at a time: the cleared ones are history
    and are never shown again.
    """
    return session.execute(
        select(StewardRecommendation)
        .where(
            StewardRecommendation.task_kind == task_kind,
            StewardRecommendation.task_id == task_id,
            StewardRecommendation.cleared.is_(False),
        )
        .order_by(StewardRecommendation.made_at.desc(), StewardRecommendation.id.desc())
    ).scalars().first()


def recommendation_by_id(
    session: Session, recommendation_id: str
) -> StewardRecommendation:
    """Return one recommendation by its identifier."""
    row = session.get(StewardRecommendation, recommendation_id)
    if row is None:
        raise NotFoundError("that recommendation does not exist")
    return row


def _entity_version(session: Session, entity_id: str) -> int:
    """Return the version of the master record an identifier names."""
    from acme_city.persistence.models import registry

    for row in (registry.Party, registry.Parcel, registry.Address):
        entity = session.get(row, entity_id)
        if entity is not None:
            return int(entity.version)
    return 0


def _open_crosswalk(session: Session, evidence: dict[str, Any]) -> Any:
    """Return the link a decision about the source record applies to."""
    from acme_city.registry.service import RegistryService

    source_system_id = str(evidence.get("source_system") or "")
    source_record_id = str(evidence.get("source_record_id") or "")
    if not source_system_id or not source_record_id:
        return None
    return RegistryService(session).open_crosswalk(source_system_id, source_record_id)


def _current_snapshot(session: Session, evidence: dict[str, Any]) -> Any:
    """Return the accepted version of the source record of the recommendation."""
    from acme_city.registry.provenance import current_accepted_snapshot

    return current_accepted_snapshot(
        session,
        str(evidence.get("source_system") or ""),
        str(evidence.get("source_dataset") or ""),
        str(evidence.get("source_record_id") or ""),
    )


def current_record_version(
    session: Session, recommendation: StewardRecommendation
) -> int:
    """Return the version of the record a recommendation read.

    The version is the one of the record the task is about: the link a match
    is decided on, the applied link of an automatic link, the parcel match of
    a property, the change case of a correction and the issue of a data
    issue.  A version that differs from the one the recommendation recorded
    means the record changed since the recommendation was made.
    """
    kind = recommendation.task_kind
    item_id = recommendation.task_id
    evidence = dict(recommendation.evidence or {})
    if kind == "link":
        row = _open_crosswalk(session, evidence)
        return int(row.version) if row is not None else 0
    if kind == "automatic_link":
        row = session.get(
            registry_automation.RegistryAutomationApplication, item_id
        )
        return int(row.version) if row is not None else 0
    if kind == "parcel":
        row = session.execute(
            select(gis.ApplicationParcelMatch).where(
                gis.ApplicationParcelMatch.application_id == item_id
            )
        ).scalars().first()
        return int(row.version) if row is not None else 0
    if kind == "case":
        row = session.get(change.ChangeCase, item_id)
        return int(row.version) if row is not None else 0
    if kind == "issue":
        row = session.get(change.GovernanceIssue, item_id)
        return int(row.version) if row is not None else 0
    return 0


def _changed_dependencies(
    session: Session, recommendation: StewardRecommendation
) -> bool:
    """Whether a fact the recommendation depended on changed since it was made.

    A recommendation of a link depends on the link it would decide on, on the
    source version it read and on the master record it compared.  A
    recommendation of an applied link depends on the link of the automation,
    on the master record that link points at and on the source version it
    read.
    """
    kind = recommendation.task_kind
    evidence = dict(recommendation.evidence or {})
    if kind == "link":
        captured_id = str(evidence.get("crosswalk_id") or "")
        captured_version = int(evidence.get("crosswalk_version") or 0)
        row = _open_crosswalk(session, evidence)
        if captured_id:
            if row is None or row.id != captured_id or int(row.version) != captured_version:
                return True
        elif row is not None:
            return True
        entity_id = str(evidence.get("candidate_entity_id") or "")
        if entity_id and _entity_version(session, entity_id) != int(
            evidence.get("candidate_version") or 0
        ):
            return True
    if kind == "automatic_link":
        captured_id = str(evidence.get("crosswalk_id") or "")
        entity_id = str(evidence.get("entity_id") or "")
        if captured_id:
            row = session.get(registry.Crosswalk, captured_id)
            if row is None or int(row.version) != int(
                evidence.get("crosswalk_version") or 0
            ):
                return True
            if entity_id and str(row.entity_id) != entity_id:
                return True
        if entity_id and _entity_version(session, entity_id) != int(
            evidence.get("entity_version") or 0
        ):
            return True
    if kind in {"link", "automatic_link"}:
        captured = str(evidence.get("source_snapshot_id") or "")
        if captured:
            current = _current_snapshot(session, evidence)
            if current is None or current.source_snapshot_id != captured:
                return True
    return False


def is_stale(session: Session, recommendation: StewardRecommendation) -> bool:
    """Whether the record of a recommendation changed since it was made."""
    if current_record_version(session, recommendation) != int(
        recommendation.record_version
    ):
        return True
    return _changed_dependencies(session, recommendation)


def refuse_unless_acceptable(
    session: Session, recommendation: StewardRecommendation
) -> None:
    """Refuse a recommendation that may not be accepted.

    A recommendation held for a person is never accepted by a button: the
    person reads the conflicting facts and decides.  A recommendation whose
    record changed since it was made is stale: the steward prepares it again.

    Raises:
        ValidationError: The recommendation is held or stale.
    """
    if recommendation.confidence == recommenders.CONFIDENCE_HELD:
        raise ValidationError(HELD_MESSAGE)
    if is_stale(session, recommendation):
        raise ValidationError(STALE_MESSAGE)


def prepare(
    session: Session,
    *,
    tasks: Sequence[recommenders.Task],
    actor: ActorContext,
    settings: Any = None,
    now: datetime | None = None,
) -> Prepared:
    """Prepare the recommendations of the tasks of one press.

    The press needs the grant of the assistant and an awake assistant.  The
    tasks are bounded: one press names at most twenty of them.  A task that
    cannot be prepared is recorded as refused and the press continues, so one
    broken task never costs the steward the rest of the work.

    Args:
        session: The open session.
        tasks: The tasks of the queue to prepare.
        actor: The person who pressed the button.
        settings: The settings of the City, so a recommendation follows the
            line the City applies.
        now: The moment of the press.

    Returns:
        The run of the press, the recommendations it recorded and the tasks it
        could not prepare.

    Raises:
        PermissionDeniedError: The person may not ask the assistant.
        ValidationError: The assistant is asleep.
    """
    moment = now or utc_now()
    control = AgentControlService(session, now=moment)
    control.authorize_manual_run(actor, AGENT_KEY)

    chosen = list(tasks)[:MAX_TASKS_PER_PRESS]
    run = agent_models.AgentRun(
        id=new_id("agentrun"),
        correlation_id=new_id("corr"),
        agent_key=AGENT_KEY,
        application_id=None,
        service_identity_id=SERVICE_ACTOR_ID,
        triggered_by=actor.actor_id,
        started_at=moment,
        finished_at=None,
        outcome="recorded",
        inputs={
            "engine": BUILTIN_ENGINE,
            "task_kinds": [task.kind for task in chosen],
            "task_ids": [task.item_id for task in chosen],
            "requested": len(tasks),
            "bounded_to": MAX_TASKS_PER_PRESS,
        },
    )
    session.add(run)
    session.flush()

    audit = AuditService(session, now=moment)
    service = _service_actor(session)
    recommendations: list[StewardRecommendation] = []
    refused: list[tuple[str, str]] = []
    for task in chosen:
        try:
            proposal = recommenders.recommend(session, task, settings=settings)
        except (NotFoundError, ValidationError) as error:
            refused.append((f"{task.kind}:{task.item_id}", str(error)))
            continue
        row = recommenders.store_recommendation(
            session,
            replace(
                proposal,
                evidence={**dict(proposal.evidence or {}), "run_id": run.id},
            ),
            actor_id=SERVICE_ACTOR_ID,
            now=moment,
        )
        recommendations.append(row)
        audit.append(
            action="steward.recommendation.prepare",
            actor=service,
            target_type="steward_recommendation",
            target_id=row.id,
            after_version=row.version,
            reason=row.reason,
            references=[run.id],
            metadata={
                "task_kind": row.task_kind,
                "task_id": row.task_id,
                "confidence": row.confidence,
                "outcome": row.outcome,
            },
        )

    run.outcome = "recommended" if recommendations else "skipped"
    run.outcome_detail = (
        f"prepared {len(recommendations)} recommendation(s); "
        f"{len(refused)} task(s) could not be prepared"
    )
    run.finished_at = moment
    session.flush()
    audit.append(
        action="steward.assist.prepare",
        actor=actor,
        target_type="agent_run",
        target_id=run.id,
        after_version=len(recommendations),
        reason=run.outcome_detail,
        references=[row.id for row in recommendations],
        metadata={
            "agent_key": AGENT_KEY,
            "requested": len(tasks),
            "prepared": len(recommendations),
            "refused": [f"{kind}:{item}" for kind, item in refused],
        },
    )
    return Prepared(
        run=run, recommendations=tuple(recommendations), refused=tuple(refused)
    )


def batch_candidates(session: Session) -> list[StewardRecommendation]:
    """Return the recommendations a batch may accept, oldest first.

    A batch accepts only what a person may act on without reading further:
    a recommendation the assistant is sure of, on a task whose decision the
    steward can take back.  A cleared recommendation is history and is never
    offered again.
    """
    rows = session.execute(
        select(StewardRecommendation)
        .where(StewardRecommendation.cleared.is_(False))
        .order_by(StewardRecommendation.made_at, StewardRecommendation.id)
    ).scalars().all()
    return [row for row in rows if recommenders.is_batch_eligible(row)]


def clear(
    session: Session,
    *,
    task_kind: str,
    task_id: str,
    actor: ActorContext,
    now: datetime | None = None,
) -> StewardRecommendation:
    """Clear the recommendation of one task.

    The steward may always clear a recommendation they do not want, also when
    the assistant sleeps.  The cleared recommendation stays in the trail: it
    is history, not a deletion.

    Args:
        session: The open session.
        task_kind: The kind of the task.
        task_id: The identifier of the task.
        actor: The person who clears the recommendation.
        now: The moment of the clearing.

    Returns:
        The cleared recommendation.

    Raises:
        PermissionDeniedError: The person may not work with the assistant.
        NotFoundError: The task holds no recommendation.
    """
    moment = now or utc_now()
    AgentControlService(session, now=moment).authorize_run(actor, AGENT_KEY)
    row = recommendation_for(session, task_kind, task_id)
    if row is None:
        raise NotFoundError("this task holds no recommendation")
    row.cleared = True
    row.cleared_at = moment
    row.version += 1
    session.flush()
    AuditService(session, now=moment).append(
        action="steward.recommendation.clear",
        actor=actor,
        target_type="steward_recommendation",
        target_id=row.id,
        after_version=row.version,
        reason="the steward cleared the recommendation",
        references=[row.id],
        metadata={"task_kind": row.task_kind, "task_id": row.task_id},
    )
    return row


__all__ = [
    "AGENT_KEY",
    "HELD_MESSAGE",
    "MAX_TASKS_PER_PRESS",
    "SERVICE_ACTOR_ID",
    "STALE_MESSAGE",
    "Prepared",
    "batch_candidates",
    "clear",
    "current_record_version",
    "is_stale",
    "prepare",
    "recommendation_by_id",
    "recommendation_for",
    "refuse_unless_acceptable",
]
