"""The endpoints of the applicant help assistant.

Three endpoints, all of them inside the applicant portal:

* ``POST /apply/help`` asks a question and records the turn;
* ``POST /apply/help/escalate`` asks a person at the City and creates the
  help request; the contact page of the City website posts here, and the
  request returns to that page;
* ``GET /apply/help/panel`` shows the panel on its own page, which is where
  the application form opens its answer so the applicant's typed fields and
  files stay intact.  The same route answers with the bare panel when the
  page asks for the fragment: that is the panel that slides up over the
  page of the applicant.

Each write checks the CSRF token, the grant of the acting persona and a
mandatory expected version, and each one is audited without the text of the
question.  A conversation belongs to the applicant who opened it: the panel
of another applicant's conversation is not found.
"""
# REQUIRES: PORTAL-02, PER-04, PER-05, SEC-03
# A question and a help request are the only writes of the assistant; each one
# checks the grant, the CSRF token and a mandatory version, and the
# conversation belongs to the applicant who opened it.

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from acme_city.applicant_help import views as help_views
from acme_city.applicant_help.service import ApplicantHelpService
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.core.errors import AcmeError, ValidationError
from acme_city.ui.portal_routes import _portal_guard, posted_form
from acme_city.ui.router import (
    CSRF_FIELD,
    error_response,
    page_context,
    render,
    ui_actor,
    verify_csrf,
)

router = APIRouter(tags=["portal"])


def _expected_version(form: Any) -> int:
    """Return the mandatory expected version of a help form.

    A missing version is refused as firmly as a stale one: the applicant must
    read the panel before it is written to.
    """
    raw = str(form.get("conversation_version", "")).strip()
    if not raw:
        raise ValidationError("an expected version is required for this action")
    try:
        return int(raw)
    except ValueError as error:
        raise ValidationError("the expected version must be a whole number") from error


def _help_return_path(
    placement: str,
    *,
    reference: str = "",
    type_key: str = "",
    conversation_id: str = "",
) -> str:
    """Return the local path a help action returns to.

    A question asked in the panel comes back to the panel: the panel has a
    page of its own, and the answer is read there.  The placement says which
    screen of the applicant the panel was opened from, so the answer knows
    the case it is about.  A request made on the contact page of the City
    website returns to that page, at the form the applicant filled in.
    """
    if placement == "contact":
        return "/city/contact#ask"
    query: dict[str, str] = {"conversation": conversation_id, "placement": placement}
    if type_key:
        query["type_key"] = type_key
    if reference:
        query["ref"] = reference
    return f"/apply/help/panel?{urlencode(query)}"


def _placement(form: Any) -> str:
    """Return the panel the help action was made from."""
    value = str(form.get("placement", "chooser")).strip()
    return value if value in help_views.PLACEMENTS else "chooser"


def _wants_json(request: Request) -> bool:
    """Return whether the caller asked for the machine-readable answer."""
    return "application/json" in request.headers.get("accept", "")


def _answer_payload(service: ApplicantHelpService, result: Any) -> dict[str, Any]:
    """Return the answer of a turn as the machine-readable mapping."""
    conversation = result.conversation
    return {
        "status": "accepted",
        "conversation_id": conversation.id,
        "conversation_version": conversation.version,
        "escalation": service.escalation_state(conversation),
        "answer": result.answer.to_dict(),
        "turns": [
            help_views.turn_view(turn, service.config)
            for turn in service.turns(conversation)
        ],
        "help_requests": [
            {
                "request_id": row.id,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "reply": row.reply or "",
            }
            for row in service.help_requests(conversation)
        ],
    }


@router.get("/apply/help/panel", operation_id="ui_portal_help_panel")
def ui_portal_help_panel(
    request: Request,
    conversation: str = "",
    type_key: str = "",
    application_id: str = "",
    reference: str = "",
    placement: str = "",
    help_question: str = "",
    fragment: str = "",
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the help panel on its own page, or as a fragment of a page.

    The page is the panel on its own: the launcher of the applicant pages
    sends the applicant there when there is no script.  The fragment is the
    same panel without the frame around it: the panel that slides up over the
    page of the applicant is fetched from here, and it carries the same
    conversation, the same citations and the same answers.
    """
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    service = ApplicantHelpService(session, settings=request.app.state.settings)
    owned = service.conversation_for(resolved, conversation)
    if conversation and owned is None:
        return error_response(
            request,
            session,
            resolved,
            status_code=404,
            title="That conversation is not available to you",
            message="No conversation with that identifier is in your records.",
            code="not_found",
            back="/apply",
        )
    panel_placement = (
        placement if placement in help_views.PANEL_PLACEMENTS else "form"
    )
    context = page_context(
        request,
        session,
        resolved,
        screen="portal",
        title="Help with your permit",
        help_question=str(help_question or "")[:1000],
        **help_views.panel_context(
            session,
            resolved,
            service=service,
            placement=panel_placement,
            permit_type_key=type_key,
            application_id=application_id,
            conversation_id=conversation,
            reference=reference,
        ),
    )
    if fragment:
        # The panel of the page: the same panel, without the frame of the
        # page around it.  Its question form opens the answer in a browsing
        # context of its own, so the page of the applicant keeps what it
        # held if the script is not there.
        return render(
            request, "components/help_panel.html", {**context, "help_in_page": True}
        )
    return render(request, "portal_help.html", context)


@router.post("/apply/help", operation_id="ui_portal_help_ask")
async def ui_portal_help_ask(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    form: Any = Depends(posted_form),
) -> Any:
    """Answer one question of the applicant and record the turn."""
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    service = ApplicantHelpService(session, settings=request.app.state.settings)
    placement = _placement(form)
    conversation_id = str(form.get("conversation_id", "")).strip()
    type_key = str(form.get("type_key", "")).strip()
    application_id = str(form.get("application_id", "")).strip()
    reference = str(form.get("return_ref", "")).strip()
    try:
        verify_csrf(request.app.state.settings, resolved, str(form.get(CSRF_FIELD, "")))
        result = service.ask(
            resolved,
            question=str(form.get("question", "")),
            expected_version=_expected_version(form),
            conversation_id=conversation_id,
            placement=placement,
            permit_type_key=type_key,
            application_id=application_id,
        )
        session.commit()
    except AcmeError as error:
        session.rollback()
        AuditService(session).record_denied(
            action="applicant.help.ask",
            actor=resolved,
            target_type="help_conversation",
            target_id=conversation_id,
            denial_reason=error.code,
        )
        session.commit()
        if _wants_json(request):
            return JSONResponse(
                status_code=error.status_code,
                content={"status": "denied", "code": error.code, "message": error.message},
            )
        return error_response(
            request,
            session,
            resolved,
            status_code=error.status_code,
            title="The question was refused",
            message=error.message,
            code=error.code,
            back="/apply",
        )
    if _wants_json(request):
        return JSONResponse(_answer_payload(service, result))
    return RedirectResponse(
        _help_return_path(
            placement,
            reference=reference,
            type_key=type_key,
            conversation_id=result.conversation.id,
        ),
        status_code=303,
    )


@router.post("/apply/help/escalate", operation_id="ui_portal_help_escalate")
async def ui_portal_help_escalate(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    form: Any = Depends(posted_form),
) -> Any:
    """Ask a person at the City to answer the applicant."""
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    service = ApplicantHelpService(session, settings=request.app.state.settings)
    placement = _placement(form)
    conversation_id = str(form.get("conversation_id", "")).strip()
    type_key = str(form.get("type_key", "")).strip()
    application_id = str(form.get("application_id", "")).strip()
    reference = str(form.get("return_ref", "")).strip()
    try:
        verify_csrf(request.app.state.settings, resolved, str(form.get(CSRF_FIELD, "")))
        request_row = service.escalate(
            resolved,
            conversation_id=conversation_id,
            expected_version=_expected_version(form),
            question=str(form.get("question", "")),
            placement=placement,
            permit_type_key=type_key,
            application_id=application_id,
        )
        session.commit()
    except AcmeError as error:
        session.rollback()
        AuditService(session).record_denied(
            action="applicant.help.escalate",
            actor=resolved,
            target_type="help_request",
            target_id=conversation_id,
            denial_reason=error.code,
        )
        session.commit()
        if _wants_json(request):
            return JSONResponse(
                status_code=error.status_code,
                content={"status": "denied", "code": error.code, "message": error.message},
            )
        if placement == "contact" and isinstance(error, ValidationError):
            # The request was made on the contact page of the City website,
            # so the reason is shown there, beside the form it was made in.
            # A refused grant and a missing record keep their own answers.
            return RedirectResponse(
                f"/city/contact?{urlencode({'error': error.message})}#ask",
                status_code=303,
            )
        return error_response(
            request,
            session,
            resolved,
            status_code=error.status_code,
            title="The request to the City was refused",
            message=error.message,
            code=error.code,
            back="/apply",
        )
    if _wants_json(request):
        return JSONResponse(
            {
                "status": "accepted",
                "help_request_id": request_row.id,
                "conversation_id": request_row.conversation_id,
                "version": request_row.version,
            }
        )
    return RedirectResponse(
        _help_return_path(
            placement,
            reference=reference,
            type_key=type_key,
            conversation_id=request_row.conversation_id,
        ),
        status_code=303,
    )


__all__ = ["router"]
