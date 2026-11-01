"""The permit life cycle page and the judge walkthrough.

``app.py`` mounts both pages only in demonstration mode, beside the persona
selector: their "Open as" buttons post to the persona switch.  They open with or
without an acting persona and change nothing.  The same module serves the steps
of the guided tour, which the browser reads to walk the same story.
"""
# REQUIRES: UX-04
# Read-only guide pages over the life cycle table and the persona switch.

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.fixtures.loader import REPO_ROOT
from acme_city.ui import guide_views
from acme_city.ui.router import page_context, persona_options, render, ui_actor

router = APIRouter(tags=["ui"])

#: The steps of the guided tour, read from the configuration.
TOUR_PATH = REPO_ROOT / "config" / "tour_steps.json"


@lru_cache(maxsize=1)
def tour_steps() -> dict[str, Any]:
    """Return the steps of the guided tour.

    The file names the persona, the screen, the control to point at and the
    caption of every step.  It changes nothing and decides nothing: the tour
    only opens screens.
    """
    return json.loads(Path(TOUR_PATH).read_text(encoding="utf-8"))


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


@router.get("/tour/steps", operation_id="ui_tour_steps")
def tour_step_list() -> Any:
    """Return the steps of the guided tour for the browser.

    The list is read-only.  The browser switches persona through the ordinary
    persona switch and opens the screens the steps name.
    """
    payload = tour_steps()
    return {
        "title": str(payload.get("title", "Take the tour")),
        "steps": list(payload.get("steps") or []),
    }


__all__ = ["router", "tour_steps"]
