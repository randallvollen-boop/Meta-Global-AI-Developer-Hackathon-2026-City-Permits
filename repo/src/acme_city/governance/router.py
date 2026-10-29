"""The governance endpoints.

Every endpoint resolves the actor from the server-held session and applies the
persisted grants.  A request body never carries authority.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_actor, get_internal_reader, get_session
from acme_city.governance.schemas import (
    DeactivateStewardCommand,
    EscalateIssueCommand,
    PreviewAuthorityChangeCommand,
    PublishAuthorityChangeCommand,
    RegisterDatasetCommand,
    ReassignStewardCommand,
)
from acme_city.governance.service import GovernanceService

router = APIRouter(prefix="/api/governance", tags=["governance"])


def governance_service(session: Session) -> GovernanceService:
    """Return a governance service bound to the request session."""
    return GovernanceService(session)


@router.get("/datasets", operation_id="list_registered_datasets")
def list_registered_datasets(
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_internal_reader),
) -> dict:
    """List every registered source dataset and whether it may publish."""
    service = governance_service(session)
    registrations = service.list_registrations()
    return {"registrations": [item.model_dump(mode="json") for item in registrations]}


@router.post("/datasets", operation_id="register_source_dataset")
def register_source_dataset(
    command: RegisterDatasetCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Register a source dataset with its responsibility."""
    service = governance_service(session)
    result = service.register_dataset(command, actor)
    return result.to_dict()


@router.post("/datasets/{dataset_key}/publish", operation_id="publish_source_dataset")
def publish_source_dataset(
    dataset_key: str,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Publish a registered dataset once its registration is complete."""
    service = governance_service(session)
    result = service.publish_dataset(dataset_key, actor)
    return result.to_dict()


@router.get("/assignments", operation_id="list_effective_assignments")
def list_effective_assignments(
    domain_id: str | None = None,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_internal_reader),
) -> dict:
    """Return the assignments that are effective now."""
    service = governance_service(session)
    assignments = service.current_assignments(domain_id)
    return {"assignments": [item.model_dump(mode="json") for item in assignments]}


@router.post("/assignments/reassign", operation_id="reassign_steward")
def reassign_steward(
    command: ReassignStewardCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Move a responsibility to another actor."""
    service = governance_service(session)
    result = service.reassign_steward(command, actor)
    return result.to_dict()


@router.post("/actors/{actor_id}/deactivate", operation_id="deactivate_steward")
def deactivate_steward(
    actor_id: str,
    command: DeactivateStewardCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Deactivate a steward, refusing when active work has no reassignment."""
    service = governance_service(session)
    result = service.deactivate_steward(
        DeactivateStewardCommand(
            actor_id=actor_id,
            reason=command.reason,
            reassign_domain_id=command.reassign_domain_id,
            reassign_to_actor_id=command.reassign_to_actor_id,
            expected_version=command.expected_version,
        ),
        actor,
    )
    return result.to_dict()


@router.post("/authority/preview", operation_id="preview_authority_change")
def preview_authority_change(
    command: PreviewAuthorityChangeCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Preview the datasets and cases an authority change would affect."""
    service = governance_service(session)
    preview = service.preview_authority_change(command, actor)
    return preview.model_dump(mode="json")


@router.post("/authority/publish", operation_id="publish_authority_change")
def publish_authority_change(
    command: PublishAuthorityChangeCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Publish an authority policy version after its impact preview."""
    service = governance_service(session)
    result = service.publish_authority_change(command, actor)
    return result.to_dict()


@router.post("/issues/escalate", operation_id="escalate_governance_issue")
def escalate_governance_issue(
    command: EscalateIssueCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Route a dispute to the accountable owner of its domain."""
    service = governance_service(session)
    result = service.escalate_issue(command, actor)
    return result.to_dict()


@router.get("/responsibility/{domain_id}", operation_id="get_domain_responsibility")
def get_domain_responsibility(
    domain_id: str,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_internal_reader),
) -> dict:
    """Return the resolved responsibility panel of a domain."""
    service = governance_service(session)
    return service.responsibility_panel(domain_id)


__all__ = ["router"]
