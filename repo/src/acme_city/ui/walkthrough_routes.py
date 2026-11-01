"""The one write of the walkthrough: a fresh copy of the café case.

``app.py`` mounts this router only in demonstration mode.  The visitor asks
for a copy of the café case, the server writes it, remembers it for the
visitor and the café path opens that copy from then on.

The copy is fictional, it is capped like the sample data of the
demonstration, it decides nothing, and it writes one audit event that says
what it did.
"""
# REQUIRES: UX-04, SEC-02
# The write needs the token of the visitor, the allowance of the
# demonstration and the audit trail.

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.core.errors import AcmeError
from acme_city.ui import judge
from acme_city.ui.router import CSRF_FIELD, error_response, ui_actor
from acme_city.walkthrough import judge_copy

router = APIRouter(tags=["ui"])

#: Where the visitor goes after the copy is made.  The copy travels in the
#: query, because the browser may follow the redirect before it has stored
#: the cookie of the copy.
DESTINATION = "/walkthrough"


@router.post("/walkthrough/start-fresh", operation_id="ui_walkthrough_start_fresh")
async def walkthrough_start_fresh(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Create a fresh copy of the café case for the visitor."""
    settings = request.app.state.settings
    if settings.is_production:
        return error_response(
            request,
            session,
            actor,
            status_code=404,
            title="That action does not exist",
            message="The demonstration copy of the café case exists in the demonstration only.",
            code="not_found",
        )
    form = await request.form()
    presented = str(form.get(CSRF_FIELD, ""))
    asked_for_json = request.query_params.get("format") == "json"
    try:
        judge.verify_write(settings, request, actor, presented)
        copy = judge_copy.create_judge_copy(
            session, actor=actor.actor_id if actor is not None else "service_walkthrough"
        )
    except AcmeError as error:
        session.rollback()
        if asked_for_json:
            return JSONResponse(
                status_code=error.status_code,
                content={"status": "denied", "code": error.code, "message": error.message},
            )
        return error_response(
            request,
            session,
            actor,
            status_code=error.status_code,
            title="The copy could not be made",
            message=error.message,
            code=error.code,
            back="/walkthrough",
        )
    if asked_for_json:
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "application_id": copy.application_id,
                "reference": copy.reference,
                "message": f"Your copy of the café case is {copy.reference}.",
            },
        )
    response = RedirectResponse(f"{DESTINATION}?case={copy.application_id}", status_code=303)
    judge.remember_copy(response, request, copy.application_id)
    return response


__all__ = ["DESTINATION", "router"]
