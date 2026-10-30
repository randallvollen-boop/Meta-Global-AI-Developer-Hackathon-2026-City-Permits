"""Processing a bounded selection of cases with the intake agent.

The bulk action is a **distinct** action: it is not the "process all waiting"
button of the intake agent screen, and it never falls through to it.  A
selection of zero cases is refused.

The selection names an application and the version it was read at.  Every
case is checked before any case runs: the grant, the record scope of the
person, the version, the state of the case and the awake state of the
agent.  The batch is all-or-nothing: it runs inside one savepoint, so a
failure anywhere in it leaves every case exactly as it was, with no run and
no audit record of a run.

Each case runs through the shared work queue, so the queue records the
attempt of every case of the selection.
"""
# REQUIRES: PER-01, PER-03, AI-03, SEC-02
# The bulk action has its own grant, refuses an empty selection, checks every
# case before it runs any of them, and either processes the whole selection
# or none of it.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from acme_city.agents.control import authorize_processing
from acme_city.agents.runtime import run_agent
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import ValidationError
from acme_city.permits.guard import require_mutable, require_not_returned
from acme_city.permits.queues import awaits_intake
from acme_city.permits.service import PERMIT_DOMAIN, PermitService
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import permit

#: The grant the bulk action needs.
PERMISSION_BULK = "permit.intake.process_selected"

#: The largest number of cases one batch may name.
MAX_SELECTION = 50


@dataclass(frozen=True)
class Selection:
    """One case of a selection, with the version it was read at."""

    application_id: str
    expected_version: int


@dataclass(frozen=True)
class BulkOutcome:
    """What the batch did."""

    processed: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    run_ids: tuple[str, ...] = ()
    details: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def _normalize(selections: list[Selection]) -> list[Selection]:
    """Return the deduplicated selection, in the order it was posted.

    A repeated case is accepted once.  A repeated case that names two
    different versions is ambiguous and is refused: the person cannot have
    read two versions of the same case at once.
    """
    if not selections:
        raise ValidationError(
            "choose at least one case to process; this action never processes every "
            "waiting case"
        )
    if len(selections) > MAX_SELECTION:
        raise ValidationError(
            f"a selection may name at most {MAX_SELECTION} cases; this one names "
            f"{len(selections)}"
        )
    seen: dict[str, int] = {}
    for entry in selections:
        application_id = str(entry.application_id or "").strip()
        if not application_id:
            raise ValidationError("a selection entry names no case")
        if application_id in seen:
            if seen[application_id] != int(entry.expected_version):
                raise ValidationError(
                    "the selection names one case at two different versions; read the "
                    "queue again and select it once"
                )
            continue
        seen[application_id] = int(entry.expected_version)
    unique: list[Selection] = []
    for entry in selections:
        application_id = str(entry.application_id or "").strip()
        if any(item.application_id == application_id for item in unique):
            continue
        unique.append(Selection(application_id, int(entry.expected_version)))
    return unique


def _in_scope(actor: ActorContext, application: permit.Application) -> bool:
    """Return whether the case is inside the record scope of the person."""
    if not actor.record_scope:
        return True
    return (
        application.source_application_number in actor.record_scope
        or (application.applicant_party_id or "") in actor.record_scope
        or application.id in actor.record_scope
    )


def process_selected(
    session: Session,
    *,
    actor: ActorContext,
    selections: list[Selection],
    settings: Any = None,
    now: datetime | None = None,
) -> BulkOutcome:
    """Run the intake agent on a bounded selection of cases.

    The whole selection is checked first; then the batch runs inside one
    savepoint, so a failure leaves every case as it was.
    """
    moment = now or utc_now()
    permissions = PermissionResolver(session, now=moment)
    permissions.authorize(
        actor,
        PERMISSION_BULK,
        ResourceContext(domain_id=PERMIT_DOMAIN, record_ids=()),
    )
    # The batch runs the intake agent, so the person who may run the agent is
    # the person who may process the selection.  The agent must be awake too:
    # a sleeping agent waits for its cases.
    authorize_processing(session, actor)
    chosen = _normalize(selections)

    permits = PermitService(session, now=moment)
    checked: list[permit.Application] = []
    for entry in chosen:
        application = permits.load_application(entry.application_id)
        if not _in_scope(actor, application):
            raise ValidationError(
                "one of the selected cases is outside the cases you may act on"
            )
        permissions.authorize(
            actor,
            PERMISSION_BULK,
            ResourceContext(
                domain_id=PERMIT_DOMAIN,
                record_ids=(
                    application.source_application_number,
                    application.applicant_party_id or "",
                ),
            ),
        )
        if application.version != entry.expected_version:
            raise ValidationError(
                "one of the selected cases changed since you read it; read the queue "
                "again and retry"
            )
        require_mutable(application, action="processing the case with the intake agent")
        require_not_returned(
            application, action="processing the case with the intake agent"
        )
        if not awaits_intake(session, application):
            raise ValidationError(
                "one of the selected cases does not wait for the intake agent; it "
                "has already been processed or it is not open"
            )
        checked.append(application)

    audit = AuditService(session, now=moment)
    processed: list[str] = []
    outcomes: list[str] = []
    run_ids: list[str] = []
    details: list[dict[str, Any]] = []
    savepoint = session.begin_nested()
    try:
        for application in checked:
            result = run_agent(
                session,
                application=application,
                agent_key=agent_models.AGENT_INTAKE,
                triggered_by=actor.actor_id,
                settings=settings,
                now=moment,
            )
            processed.append(application.id)
            outcomes.append(result.outcome)
            run_ids.append(result.run_id)
            details.append(
                {
                    "application_id": application.id,
                    "reference": application.source_application_number,
                    "outcome": result.outcome,
                    "run_id": result.run_id,
                    "status": application.status,
                }
            )
        audit.append(
            action="application.intake.process_selected",
            actor=actor,
            target_type="application",
            target_id=processed[0] if processed else "",
            reason=(
                f"processed {len(processed)} selected case(s) with the intake agent"
            ),
            references=list(run_ids),
            metadata={
                "selection_size": len(chosen),
                "application_ids": list(processed),
                "run_ids": list(run_ids),
                "outcomes": list(outcomes),
            },
        )
        savepoint.commit()
    except Exception:
        savepoint.rollback()
        raise

    session.flush()
    return BulkOutcome(
        processed=tuple(processed),
        outcomes=tuple(outcomes),
        run_ids=tuple(run_ids),
        details=tuple(details),
    )


__all__ = [
    "MAX_SELECTION",
    "PERMISSION_BULK",
    "BulkOutcome",
    "Selection",
    "process_selected",
]
