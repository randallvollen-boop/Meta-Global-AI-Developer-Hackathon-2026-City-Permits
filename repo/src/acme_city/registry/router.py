"""The registry endpoints.

Every endpoint resolves the actor from the server-held session.  A decision
needs the explicit ``registry.crosswalk.decide`` grant, the domain scope and
the expected version of the link it changes.
"""
# REQUIRES: MDM-01, MDM-02, MDM-03, MDM-04, MDM-05, GOV-05
# The registry endpoints expose proposals, steward decisions, the crosswalk
# history and the trusted view of a canonical entity.

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_actor, get_internal_reader, get_session
from acme_city.core.errors import NotFoundError
from acme_city.core.results import ConflictResult
from acme_city.registry.provenance import crosswalk_view
from acme_city.registry.schemas import (
    MatchDecisionCommand,
    MatchProposalCommand,
)
from acme_city.registry.service import RegistryService
from acme_city.persistence.models import registry

router = APIRouter(prefix="/api/registry", tags=["registry"])


def registry_service(session: Session) -> RegistryService:
    """Return a registry service bound to the request session."""
    return RegistryService(session)


def conflict_response(result: ConflictResult) -> JSONResponse:
    """Return the stable conflict envelope for a stale decision."""
    return JSONResponse(
        status_code=409,
        content={
            "code": result.code,
            "message": "the record changed since it was read; read it again and retry",
            "expected_version": result.expected_version,
            "current_version": result.current_version,
            "differences": [dict(difference) for difference in result.differences],
        },
    )


@router.post("/proposals", operation_id="propose_source_link")
def propose_source_link(
    command: MatchProposalCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Propose the candidate links of one source record."""
    service = registry_service(session)
    proposal = service.propose(command, actor)
    return proposal.model_dump(mode="json")


@router.post("/decisions", operation_id="decide_source_link")
def decide_source_link(
    command: MatchDecisionCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
):
    """Record a steward decision on a source-to-canonical link."""
    service = registry_service(session)
    result = service.decide(command, actor)
    if isinstance(result, ConflictResult):
        return conflict_response(result)
    return result.to_dict()


@router.get("/crosswalks", operation_id="list_source_links")
def list_source_links(
    source_system_id: str | None = None,
    source_record_id: str | None = None,
    entity_id: str | None = None,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_internal_reader),
) -> dict:
    """List the source links, optionally for one source record or entity."""
    statement = select(registry.Crosswalk)
    if source_system_id:
        statement = statement.where(registry.Crosswalk.source_system_id == source_system_id)
    if source_record_id:
        statement = statement.where(registry.Crosswalk.source_record_id == source_record_id)
    if entity_id:
        statement = statement.where(registry.Crosswalk.entity_id == entity_id)
    rows = session.execute(
        statement.order_by(registry.Crosswalk.created_at, registry.Crosswalk.id)
    ).scalars().all()
    return {
        "crosswalks": [crosswalk_view(row).model_dump(mode="json") for row in rows]
    }


@router.get("/crosswalks/history", operation_id="list_source_link_history")
def list_source_link_history(
    source_system_id: str,
    source_record_id: str,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_internal_reader),
) -> dict:
    """Return every decision of one source record, oldest first."""
    service = registry_service(session)
    views = service.crosswalk_history(source_system_id, source_record_id)
    return {"crosswalks": [view.model_dump(mode="json") for view in views]}


@router.get("/entities/{entity_id}/trusted-view", operation_id="get_trusted_view")
def get_trusted_view(
    entity_id: str,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_internal_reader),
) -> dict:
    """Return the trusted view of one canonical entity."""
    service = registry_service(session)
    view = service.trusted_view(entity_id)
    if view is None:
        raise NotFoundError(f"no canonical entity {entity_id!r} exists")
    return view.model_dump(mode="json")


__all__ = ["conflict_response", "registry_service", "router"]
