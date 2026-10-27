"""The rule and fee catalogue endpoints.

Every endpoint resolves the actor from the server-held session and applies the
persisted grants.  A request body never carries authority, and a publication
is refused when it would overlap a version that is already in force.
"""
# REQUIRES: REF-01, REF-02, PER-02, PER-06, SEC-03
# Retrieval, execution and citation share one selected version, and the
# catalogue lifecycle is a separate authorized transition.

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_actor, get_session
from acme_city.core.clock import utc_now
from acme_city.core.results import ConflictResult
from acme_city.rules.schemas import (
    DraftFeeScheduleCommand,
    DraftRuleCommand,
    FeeScheduleLifecycleCommand,
    PublishRuleCommand,
    RetireRuleCommand,
    RuleLifecycleCommand,
)
from acme_city.rules.service import RuleCatalogService

router = APIRouter(prefix="/api/rules", tags=["rules"])


def catalog_service(session: Session) -> RuleCatalogService:
    """Return a catalogue service bound to the request session."""
    return RuleCatalogService(session)


def _respond(result: object) -> object:
    """Return a conflict as a 409 and an accepted change as a 200."""
    if isinstance(result, ConflictResult):
        return JSONResponse(status_code=409, content=result.to_dict())
    return result.to_dict()


@router.get("", operation_id="list_rule_versions")
def list_rule_versions(
    permit_type: str | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """List the stored rule versions."""
    service = catalog_service(session)
    versions = service.list_versions(permit_type, status=status)
    return {"versions": [item.model_dump(mode="json") for item in versions]}


@router.get("/resolve", operation_id="resolve_rule_set")
def resolve_rule_set(
    kind: str = Query(default="executable"),
    permit_type: str | None = None,
    basis_at: datetime | None = None,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Return the catalogue versions in force at a basis date."""
    service = catalog_service(session)
    basis = basis_at or utc_now()
    rule_set = service.resolve(kind, permit_type, basis)
    return rule_set.model_dump(mode="json")


@router.post("/fee-schedules", operation_id="draft_fee_schedule_version")
def draft_fee_schedule_version(
    command: DraftFeeScheduleCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Create a new draft fee schedule version."""
    service = catalog_service(session)
    result = service.draft_fee_schedule(command, actor)
    return result.to_dict()


@router.post(
    "/fee-schedules/{fee_schedule_version_id}/submit",
    operation_id="submit_fee_schedule_version",
)
def submit_fee_schedule_version(
    fee_schedule_version_id: str,
    command: FeeScheduleLifecycleCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Move a draft fee schedule version into review."""
    service = catalog_service(session)
    result = service.submit_fee_schedule_for_review(
        FeeScheduleLifecycleCommand(
            fee_schedule_version_id=fee_schedule_version_id,
            expected_version=command.expected_version,
            reason=command.reason,
        ),
        actor,
    )
    return _respond(result)


@router.post(
    "/fee-schedules/{fee_schedule_version_id}/approve",
    operation_id="approve_fee_schedule_version",
)
def approve_fee_schedule_version(
    fee_schedule_version_id: str,
    command: FeeScheduleLifecycleCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Approve a fee schedule version that somebody else authored."""
    service = catalog_service(session)
    result = service.approve_fee_schedule(
        FeeScheduleLifecycleCommand(
            fee_schedule_version_id=fee_schedule_version_id,
            expected_version=command.expected_version,
            reason=command.reason,
        ),
        actor,
    )
    return _respond(result)


@router.post(
    "/fee-schedules/{fee_schedule_version_id}/publish",
    operation_id="publish_fee_schedule_version",
)
def publish_fee_schedule_version(
    fee_schedule_version_id: str,
    command: FeeScheduleLifecycleCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Publish an approved fee schedule version."""
    service = catalog_service(session)
    result = service.publish_fee_schedule(
        FeeScheduleLifecycleCommand(
            fee_schedule_version_id=fee_schedule_version_id,
            expected_version=command.expected_version,
            reason=command.reason,
            precedence=command.precedence,
        ),
        actor,
    )
    return _respond(result)


@router.post(
    "/fee-schedules/{fee_schedule_version_id}/retire",
    operation_id="retire_fee_schedule_version",
)
def retire_fee_schedule_version(
    fee_schedule_version_id: str,
    command: FeeScheduleLifecycleCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Retire a published fee schedule version."""
    service = catalog_service(session)
    result = service.retire_fee_schedule(
        FeeScheduleLifecycleCommand(
            fee_schedule_version_id=fee_schedule_version_id,
            expected_version=command.expected_version,
            reason=command.reason,
        ),
        actor,
    )
    return _respond(result)


@router.get("/{rule_version_id}", operation_id="get_rule_version")
def get_rule_version(
    rule_version_id: str,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Return one stored rule version."""
    service = catalog_service(session)
    return service.get_version(rule_version_id).model_dump(mode="json")


@router.post("", operation_id="draft_rule_version")
def draft_rule_version(
    command: DraftRuleCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Create a new draft rule version."""
    service = catalog_service(session)
    result = service.draft(command, actor)
    return result.to_dict()


@router.post("/{rule_version_id}/submit", operation_id="submit_rule_version")
def submit_rule_version(
    rule_version_id: str,
    command: RuleLifecycleCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Move a draft rule version into review."""
    service = catalog_service(session)
    result = service.submit_for_review(
        RuleLifecycleCommand(
            rule_version_id=rule_version_id,
            expected_version=command.expected_version,
            reason=command.reason,
        ),
        actor,
    )
    return _respond(result)


@router.post("/{rule_version_id}/approve", operation_id="approve_rule_version")
def approve_rule_version(
    rule_version_id: str,
    command: RuleLifecycleCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Approve a rule version that somebody else authored."""
    service = catalog_service(session)
    result = service.approve(
        RuleLifecycleCommand(
            rule_version_id=rule_version_id,
            expected_version=command.expected_version,
            reason=command.reason,
        ),
        actor,
    )
    return _respond(result)


@router.post("/{rule_version_id}/publish", operation_id="publish_rule_version")
def publish_rule_version(
    rule_version_id: str,
    command: PublishRuleCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Publish an approved rule version."""
    service = catalog_service(session)
    result = service.publish(
        PublishRuleCommand(
            rule_version_id=rule_version_id,
            expected_version=command.expected_version,
            reason=command.reason,
            precedence=command.precedence,
        ),
        actor,
    )
    return _respond(result)


@router.post("/{rule_version_id}/retire", operation_id="retire_rule_version")
def retire_rule_version(
    rule_version_id: str,
    command: RetireRuleCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Retire a published rule version."""
    service = catalog_service(session)
    result = service.retire(
        RetireRuleCommand(
            rule_version_id=rule_version_id,
            expected_version=command.expected_version,
            reason=command.reason,
            effective_to=command.effective_to,
        ),
        actor,
    )
    return _respond(result)


__all__ = ["router"]
