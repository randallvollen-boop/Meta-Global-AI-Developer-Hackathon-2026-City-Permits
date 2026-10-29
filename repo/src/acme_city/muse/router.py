"""The bounded model endpoints.

Only a staff actor that holds the explicit grants may request model work, and
only the actor's own scope decides which records a run may read.  A run is
always recorded, so the endpoint answers with the recorded run: a failed
validation is a recorded failure, not a missing answer.
"""
# REQUIRES: AI-01, AI-02, AI-03, AI-04, SEC-02
# The Muse endpoints resolve the actor from the server-held session, accept a bounded command
# and return the recorded run. An applicant never reaches them.

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_actor, get_session
from acme_city.muse.service import MuseRunCommand, MuseService

router = APIRouter(prefix="/api/muse", tags=["muse"])


def muse_service(request: Request, session: Session) -> MuseService:
    """Return a model service bound to the request session."""
    return MuseService(session, request.app.state.settings)


@router.post("/run", operation_id="run_muse_task")
def run_muse_task(
    command: MuseRunCommand,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Run one bounded model task and return the recorded run.

    The command names the task, the mode and the records.  It never carries
    authority: the server resolves the actor, the scope and the model.
    """
    service = muse_service(request, session)
    view = service.run(command, actor)
    return view.model_dump(mode="json")


@router.get("/runs", operation_id="list_muse_runs")
def list_muse_runs(
    request: Request,
    application_id: str | None = None,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Return the recorded model runs the actor may read."""
    service = muse_service(request, session)
    views = service.list_runs(actor, application_id=application_id)
    return {"runs": [view.model_dump(mode="json") for view in views]}


__all__ = ["muse_service", "router"]
