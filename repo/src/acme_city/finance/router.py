"""The finance endpoints.

Every endpoint resolves the actor from the server-held session and applies the
persisted grants.  Amounts cross the boundary as decimal strings; the server
validates the currency and stores integer cents.
"""
# REQUIRES: FIN-01, FIN-02, FIN-03, FIN-04, FIN-05, SEC-03
# Assessment, payment import, allocation and reconciliation are separate
# authorized Finance actions.

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_actor, get_session
from acme_city.core.results import ConflictResult
from acme_city.finance.schemas import (
    AllocationCommand,
    AssessmentCommand,
    PaymentEventCommand,
    ReassessmentCommand,
    ReconciliationCommand,
)
from acme_city.finance.service import FinanceService

router = APIRouter(prefix="/api/finance", tags=["finance"])


def finance_service(session: Session) -> FinanceService:
    """Return a finance service bound to the request session."""
    return FinanceService(session)


def _respond(result: object) -> object:
    """Return a conflict as a 409 and an accepted change as a 200."""
    if isinstance(result, ConflictResult):
        return JSONResponse(status_code=409, content=result.to_dict())
    return result.to_dict()


@router.post("/assessments", operation_id="assess_application")
def assess_application(
    command: AssessmentCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Assess the declared valuation of an application."""
    service = finance_service(session)
    return service.assess(command, actor).model_dump(mode="json")


@router.post("/assessments/reassess", operation_id="reassess_application")
def reassess_application(
    command: ReassessmentCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Assess an application again at a new valuation."""
    service = finance_service(session)
    return service.reassess(command, actor).model_dump(mode="json")


@router.post("/payments", operation_id="import_payment_event")
def import_payment_event(
    command: PaymentEventCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Import one simulated ERP payment event."""
    service = finance_service(session)
    result = service.import_payment(command, actor)
    if isinstance(result, ConflictResult):
        return _respond(result)
    return result.model_dump(mode="json")


@router.post("/allocations", operation_id="confirm_allocation")
def confirm_allocation(
    command: AllocationCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Confirm an allocation of settled funds to an assessment version."""
    service = finance_service(session)
    result = service.allocate(command, actor)
    if isinstance(result, ConflictResult):
        return _respond(result)
    return result.model_dump(mode="json")


@router.post("/reconciliations", operation_id="reconcile_assessment")
def reconcile_assessment(
    command: ReconciliationCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Reconcile an assessment version against its receipts."""
    service = finance_service(session)
    return service.reconcile(command, actor).model_dump(mode="json")


__all__ = ["router"]
