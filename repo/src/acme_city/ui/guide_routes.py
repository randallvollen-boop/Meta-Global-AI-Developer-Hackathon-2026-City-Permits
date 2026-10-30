"""The permit life cycle page and the judge walkthrough.

``app.py`` mounts both pages only in demonstration mode, beside the persona
selector: their "Open as" buttons post to the persona switch.  They open with or
without an acting persona and change nothing.
"""
# REQUIRES: UX-04
# Read-only guide pages over the life cycle table and the persona switch.

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.ui import guide_views
from acme_city.ui.router import page_context, persona_options, render, ui_actor

router = APIRouter(tags=["ui"])


def _context(
    request: Request, session: Session, actor: ActorContext | None, *, screen: str, title: str, **extra: Any
) -> dict[str, Any]:
    if actor is not None:
        return page_context(request, session, actor, screen=screen, title=title, **extra)
    return {
        "screen": screen,
        "title": title,
        "personas": persona_options(session),
        "navigation": [],
        "feedback": None,
        "csrf_token": "",
        "fictional_demo": True,
        "actor": None,
        **extra,
    }


@router.get("/lifecycle", operation_id="ui_permit_lifecycle")
def permit_lifecycle(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show every status of a permit application and every move between them."""
    context = _context(
        request, session, actor, screen="lifecycle", title="Permit life cycle",
        lifecycle=guide_views.lifecycle_view(session),
    )
    return render(request, "lifecycle.html", context)


@router.get("/walkthrough", operation_id="ui_judge_walkthrough")
def judge_walkthrough(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the numbered path through the app for a first-time visitor."""
    context = _context(
        request, session, actor, screen="walkthrough", title="Walkthrough",
        walkthrough=guide_views.walkthrough_view(session),
    )
    return render(request, "walkthrough.html", context)


__all__ = ["router"]
