"""The permit life cycle page and the judge walkthrough.

``app.py`` mounts both pages only in demonstration mode, beside the persona
selector: their "Open as" buttons post to the persona switch.  They open with or
without an acting persona and change nothing.  The same module serves the steps
of the guided tour, which the browser reads to walk the same story.

The tour is served path by path.  The browser asks for the path it walks, and
the steps of that path are the steps of the written walkthrough.  The screen
of a step may name the case of the café path, which is the copy the visitor
made with Start fresh when there is one.
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
from acme_city.ui import guide_views, judge
from acme_city.ui.router import (
    page_context,
    persona_options,
    render,
    ui_actor,
)

router = APIRouter(tags=["ui"])

#: The steps of the guided tour, read from the configuration.
TOUR_PATH = REPO_ROOT / "config" / "tour_steps.json"


@lru_cache(maxsize=1)
def tour_steps() -> dict[str, Any]:
    """Return the steps of the guided tour.

    The file names the paths, and every path names the persona, the screen,
    the control to point at and the caption of every step.  It changes nothing
    and decides nothing: the tour only opens screens.
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
    """Show the paths of the walkthrough, each with its own steps."""
    asked_for = str(request.query_params.get("case") or "")
    case_id = asked_for or judge.copy_case_id(request) or guide_views.DEFAULT_CASE_ID
    visitor = judge.page_context(request)
    context = _context(
        request, session, actor, screen="walkthrough", title="Walkthrough",
        walkthrough=guide_views.walkthrough_view(session, case_id=case_id),
        judge=visitor,
    )
    response = render(request, "walkthrough.html", context)
    judge.attach(response, request, visitor)
    if asked_for:
        # The copy travels in the query, so the walkthrough remembers it for
        # the tour that follows.
        judge.remember_copy(response, request, asked_for)
    return response


@router.get("/tour/steps", operation_id="ui_tour_steps")
def tour_step_list(request: Request, path: str = "") -> Any:
    """Return the steps of one path of the guided tour for the browser.

    The list is read-only.  The browser switches persona through the ordinary
    persona switch and opens the screens the steps name.
    """
    payload = tour_steps()
    paths = dict(payload.get("paths") or {})
    # An unnamed request, and a name that is not a path, opens the configured
    # default. That stays the café path when the file lists the resident path first.
    named = str(payload.get("default_path") or "")
    key = path or named
    if key not in paths:
        key = named if named in paths else next(iter(paths), "")
    chosen = dict(paths.get(key) or {})
    case_id = judge.copy_case_id(request) or guide_views.DEFAULT_CASE_ID
    steps = [
        {
            **dict(step),
            "path": guide_views.resolve_path(str(step.get("path", "")), case_id),
            "path_key": key,
            "path_title": str(chosen.get("title", "")),
        }
        for step in (chosen.get("steps") or [])
    ]
    return {
        "title": str(payload.get("title", "Take the tour")),
        "path": key,
        "paths": [
            {
                "key": name,
                "title": str(value.get("title", "")),
                "minutes": int(value.get("minutes", 0) or 0),
            }
            for name, value in paths.items()
        ],
        "steps": steps,
    }


__all__ = ["router", "tour_steps"]
