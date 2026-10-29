"""The permit workflow endpoints.

Every endpoint resolves the actor from the server-held session and applies the
persisted grants.  A request body never carries authority: a ruling that
arrives without an authorized transition is refused before it reaches the
service.
"""
# REQUIRES: PER-01, PER-02, PER-03, PER-04, PER-06, SEC-02, SEC-03
# Submission, revision, evaluation, decision and issuance are separate
# authorized actions, and a record outside the actor's scope is refused.

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_actor, get_session
from acme_city.core.errors import NotFoundError, PermissionDeniedError
from acme_city.core.results import ConflictResult
from acme_city.documents.service import DocumentService, StoreDocumentCommand
from acme_city.permits.comments import comment_view, comments_for
from acme_city.permits.decisions import PermitDecisionCommand
from acme_city.permits.impact import ChangeImpactCommand, ImpactService
from acme_city.permits.issuance import IssuePermitCommand
from acme_city.permits.schemas import ReviseApplicationCommand, SubmitApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.persistence.models import permit

router = APIRouter(prefix="/api/permits", tags=["permits"])


def permit_service(session: Session) -> PermitService:
    """Return a permit service bound to the request session."""
    return PermitService(session)


def document_service(session: Session) -> DocumentService:
    """Return a document service bound to the request session."""
    return DocumentService(session)


def _respond(result: object) -> object:
    """Return a conflict as a 409 and an accepted change as a 200."""
    if isinstance(result, ConflictResult):
        return JSONResponse(status_code=409, content=result.to_dict())
    return result.to_dict()


def _require_application_scope(
    application: permit.Application, actor: ActorContext
) -> None:
    """Refuse a direct application read outside the server-resolved record scope."""
    if not actor.record_scope:
        return
    visible_ids = {
        application.source_application_number,
        application.applicant_party_id or "",
    }
    if visible_ids.intersection(actor.record_scope):
        return
    raise PermissionDeniedError(
        "that application is outside the actor's record scope",
        actor_id=actor.actor_id,
        action="application.read",
        target_type="application",
        target_id=application.id,
    )


def _load_visible_application(
    service: PermitService, application_id: str, actor: ActorContext
) -> permit.Application:
    application = service.load_application(application_id)
    _require_application_scope(application, actor)
    return application


@router.get("/applications", operation_id="list_applications")
def list_applications(
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """List the applications the actor may see."""
    service = permit_service(session)
    applications = session.execute(
        select(permit.Application).order_by(permit.Application.source_application_number)
    ).scalars().all()
    visible = [
        application
        for application in applications
        if not actor.record_scope
        or application.source_application_number in actor.record_scope
        or (application.applicant_party_id or "") in actor.record_scope
    ]
    return {
        "applications": [
            service.application_view(application).model_dump(mode="json")
            for application in visible
        ]
    }


@router.post("/applications", operation_id="submit_application")
def submit_application(
    command: SubmitApplicationCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Submit an application and record its first immutable revision."""
    service = permit_service(session)
    return service.submit(command, actor).model_dump(mode="json")


@router.get("/applications/{application_id}", operation_id="get_application")
def get_application(
    application_id: str,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Return an application and its latest submitted revision."""
    service = permit_service(session)
    application = _load_visible_application(service, application_id, actor)
    return service.application_view(application).model_dump(mode="json")


@router.post("/applications/{application_id}/revisions", operation_id="revise_application")
def revise_application(
    application_id: str,
    command: ReviseApplicationCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Create a new submitted revision of an application."""
    service = permit_service(session)
    result = service.revise(
        ReviseApplicationCommand(
            application_id=application_id,
            facts=command.facts,
            parties=command.parties,
            site=command.site,
            reason=command.reason,
            expected_version=command.expected_version,
        ),
        actor,
    )
    if isinstance(result, ConflictResult):
        return _respond(result)
    return result.model_dump(mode="json")


@router.post("/applications/{application_id}/evaluate", operation_id="evaluate_application")
def evaluate_application(
    application_id: str,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Evaluate the current revision against the selected rule versions."""
    service = permit_service(session)
    return service.evaluate(application_id, actor).model_dump(mode="json")


@router.get(
    "/applications/{application_id}/evaluations", operation_id="list_evaluations"
)
def list_evaluations(
    application_id: str,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Return the evaluations of an application."""
    service = permit_service(session)
    _load_visible_application(service, application_id, actor)
    rows = session.execute(
        select(permit.Evaluation)
        .where(permit.Evaluation.application_id == application_id)
        .order_by(permit.Evaluation.version)
    ).scalars().all()
    return {
        "evaluations": [
            service.evaluation_view(row).model_dump(mode="json") for row in rows
        ]
    }


@router.post("/applications/{application_id}/decisions", operation_id="decide_application")
def decide_application(
    application_id: str,
    command: PermitDecisionCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Record an actual reviewer decision.

    An approval that carries conditions is an ``approved`` decision with a
    non-empty conditions list; the decision outcome vocabulary does not
    change.
    """
    service = permit_service(session)
    result = service.decide(
        PermitDecisionCommand(
            application_id=application_id,
            outcome=command.outcome,
            reason=command.reason,
            conditions=list(command.conditions or []),
            reason_code=command.reason_code,
            expected_application_version=command.expected_application_version,
            expected_evaluation_version=command.expected_evaluation_version,
        ),
        actor,
    )
    return _respond(result)


@router.post(
    "/applications/{application_id}/reconfirm", operation_id="reconfirm_application"
)
def reconfirm_application(
    application_id: str,
    command: PermitDecisionCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Record a reviewer reconfirmation of a stale decision.

    The reconfirmation carries the conditions of the decision it replaces, so
    the conditions survive the round trip.
    """
    service = permit_service(session)
    result = service.reconfirm(
        PermitDecisionCommand(
            application_id=application_id,
            outcome=command.outcome,
            reason=command.reason,
            conditions=list(command.conditions or []),
            reason_code=command.reason_code,
            expected_application_version=command.expected_application_version,
            expected_evaluation_version=command.expected_evaluation_version,
        ),
        actor,
    )
    return _respond(result)


@router.post("/applications/{application_id}/issue", operation_id="issue_permit")
def issue_permit(
    application_id: str,
    command: IssuePermitCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> object:
    """Issue a simulated permit from a current approved decision."""
    service = permit_service(session)
    result = service.issue(
        IssuePermitCommand(
            application_id=application_id,
            decision_id=command.decision_id,
            expected_application_version=command.expected_application_version,
            expected_decision_version=command.expected_decision_version,
            command_key=command.command_key,
            reason=command.reason,
        ),
        actor,
    )
    return _respond(result)


@router.get(
    "/applications/{application_id}/documents", operation_id="list_document_versions"
)
def list_document_versions(
    application_id: str,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Return the stored document versions of an application."""
    _load_visible_application(permit_service(session), application_id, actor)
    service = document_service(session)
    versions = service.list_versions(application_id)
    return {"documents": [item.model_dump(mode="json") for item in versions]}


@router.post("/applications/{application_id}/documents", operation_id="store_document_version")
async def store_document_version(
    application_id: str,
    document_type: str = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Store one document version with the bytes that were received."""
    service = document_service(session)
    content = await file.read()
    command = StoreDocumentCommand(
        application_id=application_id,
        document_type=document_type,
        filename=file.filename or "",
        media_type=file.content_type or "",
        content=content,
    )
    return service.store_version(command, actor).model_dump(mode="json")


@router.get("/documents/{document_id}/content", operation_id="download_document_version")
def download_document_version(
    document_id: str,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> Response:
    """Return the bytes of one stored document version."""
    row = session.get(permit.Document, document_id)
    if row is None or row.application_id is None:
        raise NotFoundError("that document does not exist")
    _load_visible_application(permit_service(session), row.application_id, actor)
    service = document_service(session)
    content = service.read_bytes(document_id)
    return Response(
        content=content,
        media_type="application/octet-stream",
        # A stored applicant document must not be kept by a shared or local cache.
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/applications/{application_id}/comments", operation_id="list_application_comments"
)
def list_application_comments(
    application_id: str,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Return the comments of an application the actor may read.

    An applicant reads only the comments the City wrote for the applicant.
    """
    _load_visible_application(permit_service(session), application_id, actor)
    rows = comments_for(session, application_id, actor)
    return {"comments": [comment_view(row) for row in rows]}


@router.get("/comments/{comment_id}", operation_id="get_application_comment")
def get_application_comment(
    comment_id: str,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Return one comment of an application the actor may read.

    A comment outside the actor's scope is refused, and an internal comment
    is refused for an applicant: the identifier of an internal note is not a
    way to read it.
    """
    row = session.get(permit.ApplicationComment, comment_id)
    if row is None or row.application_id is None:
        raise NotFoundError("that comment does not exist")
    _load_visible_application(permit_service(session), row.application_id, actor)
    if row not in comments_for(session, row.application_id, actor):
        raise NotFoundError("that comment does not exist")
    return comment_view(row)


@router.post("/impacts", operation_id="apply_change_impact")
def apply_change_impact(
    command: ChangeImpactCommand,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Apply the impact of a source or catalogue change to the permit history."""
    service = ImpactService(session)
    summary = service.apply_change(command, actor)
    return summary.model_dump(mode="json")


__all__ = ["router"]
