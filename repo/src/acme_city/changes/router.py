"""The change endpoints.

Every endpoint resolves the actor from the server-held session.  A transition
is a server decision: the client asks for one, and the server decides whether
it is allowed.
"""
# REQUIRES: CHG-01, CHG-02, CHG-03, CHG-06, EDIT-02, EDIT-03
# The change endpoints expose the request, the permitted transitions, the impact
# preview and the dispatch run.

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.auth.router import get_actor, get_session
from acme_city.changes.dispatcher import ChangeDispatcher
from acme_city.changes.schemas import (
    ChangeRequestCommand,
    ChangeTransitionCommand,
    ImpactPreviewCommand,
)
from acme_city.changes.service import ChangeService
from acme_city.core.errors import NotFoundError, PermissionDeniedError
from acme_city.core.results import ConflictResult
from acme_city.persistence.models import change

router = APIRouter(prefix="/api/changes", tags=["changes"])


def change_service(session: Session) -> ChangeService:
    """Return a change service bound to the request session."""
    return ChangeService(session)


def conflict_response(result: ConflictResult) -> JSONResponse:
    """Return the stable conflict envelope for a stale change."""
    return JSONResponse(
        status_code=409,
        content={
            "code": result.code,
            "message": "the change case changed since it was read; read it again and retry",
            "expected_version": result.expected_version,
            "current_version": result.current_version,
            "differences": [dict(difference) for difference in result.differences],
        },
    )


@router.post("", operation_id="request_change")
def request_change(
    command: ChangeRequestCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Request a correction of a source fact or an identity link."""
    service = change_service(session)
    view = service.request(command, actor)
    return view.model_dump(mode="json")


@router.get("", operation_id="list_change_cases")
def list_change_cases(
    status: str | None = None,
    target_id: str | None = None,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """List the change cases, optionally by state or target."""
    statement = select(change.ChangeCase)
    if status:
        statement = statement.where(change.ChangeCase.status == status)
    if target_id:
        statement = statement.where(change.ChangeCase.target_id == target_id)
    rows = session.execute(
        statement.order_by(change.ChangeCase.created_at, change.ChangeCase.id)
    ).scalars().all()
    service = change_service(session)
    return {
        "change_cases": [service.case_view(row).model_dump(mode="json") for row in rows]
    }


@router.get("/{change_case_id}", operation_id="get_change_case")
def get_change_case(
    change_case_id: str,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Return one change case with its commands, dependencies and tasks."""
    case = session.get(change.ChangeCase, change_case_id)
    if case is None:
        raise NotFoundError(f"no change case {change_case_id!r} exists")
    service = change_service(session)
    return service.case_view(case).model_dump(mode="json")


@router.post("/{change_case_id}/transition", operation_id="transition_change_case")
def transition_change_case(
    change_case_id: str,
    command: ChangeTransitionCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
):
    """Move a change case to the next permitted state."""
    service = change_service(session)
    payload = command.model_copy(update={"change_case_id": change_case_id})
    result = service.transition(payload, actor)
    if isinstance(result, ConflictResult):
        return conflict_response(result)
    return result.to_dict()


@router.get("/{change_case_id}/impact", operation_id="preview_change_case_impact")
def preview_change_case_impact(
    change_case_id: str,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Show the records that a change case would affect."""
    case = session.get(change.ChangeCase, change_case_id)
    if case is None:
        raise NotFoundError(f"no change case {change_case_id!r} exists")
    service = change_service(session)
    preview = service.preview_impact(
        ImpactPreviewCommand(
            target_type=case.target_type,
            target_id=case.target_id,
            change_case_id=case.id,
        ),
        actor,
    )
    return preview.model_dump(mode="json")


@router.post("/impact/preview", operation_id="preview_change_impact")
def preview_change_impact(
    command: ImpactPreviewCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Show which records a change would affect before it is approved."""
    service = change_service(session)
    preview = service.preview_impact(command, actor)
    return preview.model_dump(mode="json")


@router.post("/dispatch", operation_id="dispatch_pending_changes")
def dispatch_pending_changes(
    limit: int = 25,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Send the pending source commands and deliver the pending publications."""
    grants = PermissionResolver(session).grants_for(actor.actor_id)
    if not any(grant.action == "change.case.transition" for grant in grants):
        raise PermissionDeniedError(
            f"actor {actor.actor_id} may not dispatch pending changes",
            actor_id=actor.actor_id,
            action="change.case.transition",
        )
    dispatcher = ChangeDispatcher(session)
    summary = dispatcher.dispatch_pending(limit=limit)
    return summary.model_dump(mode="json")


__all__ = ["change_service", "conflict_response", "router"]
