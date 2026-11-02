"""The permit life cycle page and the judge walkthrough.

``app.py`` mounts both pages only in demonstration mode, beside the persona
selector: their "Open as" buttons post to the persona switch.  They open with or
without an acting persona and change nothing.  The same module serves the steps
of the guided tour, which the browser reads to walk the same story.

The browser asks for the path it walks.  Take the tour, with no path named,
runs the resident, the café and the city in that order, with one line between
tracks.  A name that is not a path still opens the café path.  The screen of
a step may name the case of the café path, which is the copy the visitor made
with Start fresh when there is one.
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


#: The label the intake screen prints on a recorded reading.
INTAKE_REPLAY_LABEL = "Recorded replay"

#: The link on the permit card.  It opens the public search already filled in.
SEARCH_FOR_MY_PERMIT = "Search for my permit"

#: The note the what-if screen prints when live Muse is off.
POLICY_REPLAY_LABEL = (
    "Live Muse calls are off. Muse answers come from recorded demonstration fixtures only."
)

#: The one line between two tracks.  The key is the track that comes next.
#: The title differs from the story intro of that track.
_BRIDGE_COPY = {
    "cafe": (
        "Get the café open",
        (
            "The resident's case is in. Now the City clears a café that "
            "has been waiting for weeks."
        ),
    ),
    "city": (
        "Run the city",
        (
            "The café permit is on the public record. Cafés like Cedarline "
            "waited weeks. Should the City change the commercial fee, or the "
            "process?"
        ),
    ),
}


def _story_keys() -> tuple[str, ...]:
    """Return the three tracks Take the tour walks, in the order of the page."""
    return tuple(path.key for path in guide_views.PATHS if path.key != "before")


def _allowance_spent(session: Session, settings: Any) -> bool:
    """Return whether the daily Muse allowance is already used up.

    This only reads the counter.  The tour never reserves a call.
    """
    from acme_city.muse.budget import MuseBudget

    budget = MuseBudget(session, settings=settings)
    cap = budget.cap
    if cap <= 0:
        return True
    return budget.used() >= cap


def _surface_live(session: Session, settings: Any, surface: str) -> bool:
    """Return whether this Muse surface may call live Muse right now."""
    if surface == "help":
        return bool(getattr(settings, "applicant_assist_live_enabled", False))
    if surface == "presubmit":
        return bool(getattr(settings, "presubmit_review_live_enabled", False))
    if surface == "intake":
        # Document reading is a recorded Muse run by design. The tour says so
        # even when a live flag is on. Live Muse is the help assistant, Check
        # my application, Explain with Muse, and the policy briefing.
        return False
    if surface == "policy":
        return bool(getattr(settings, "policy_assist_live_enabled", False))
    if surface == "explain":
        from acme_city.ui.steward_assist_views import explain_state

        return bool(explain_state(session, settings).get("available"))
    return False


def _replay_label(session: Session, settings: Any, surface: str) -> str:
    """Return the label the screen already prints when Muse is not live."""
    if surface == "help":
        from acme_city.applicant_help.config import load_config

        return str(load_config().replay_label)
    if surface == "presubmit":
        from acme_city.applicant_portal.presubmit import ASSISTANT_OFFLINE

        return ASSISTANT_OFFLINE
    if surface == "intake":
        return INTAKE_REPLAY_LABEL
    if surface == "policy":
        return POLICY_REPLAY_LABEL
    if surface == "explain":
        from acme_city.ui.steward_assist_views import explain_state

        return str(explain_state(session, settings).get("note") or "")
    return ""


def _replay_note(step: dict[str, Any], session: Session, settings: Any, spent: bool) -> str:
    """Return the replay line for a Muse step, or nothing when that Muse is live.

    The line is not part of the caption.  The panel shows it on its own, and
    it quotes the label the screen already uses.
    """
    if not step.get("muse"):
        return ""
    surface = str(step.get("muse_surface") or "")
    if not spent and _surface_live(session, settings, surface):
        return ""
    label = _replay_label(session, settings, surface)
    return (
        "The answer comes from the recorded replay. "
        f"On screen it is labelled {label}."
    )


def _present_step(
    step: dict[str, Any],
    *,
    key: str,
    title: str,
    case_id: str,
    session: Session,
    settings: Any,
    spent: bool,
) -> dict[str, Any]:
    """Return one step for the browser, without changing the cached file."""
    item = dict(step)
    item["path"] = guide_views.resolve_path(str(step.get("path", "")), case_id)
    item["path_key"] = key
    item["path_title"] = title
    item["replay_note"] = _replay_note(step, session, settings, spent)
    if step.get("permit_card"):
        card = guide_views.permit_card(session, case_id)
        if card:
            card["search_label"] = SEARCH_FOR_MY_PERMIT
            item["permit"] = card
            # The public step names this judge's permit, so the search is not a guess.
            ending = "Search the public record."
            caption = str(item.get("caption") or "")
            if step.get("id") == "public" and caption.endswith(ending):
                item["caption"] = caption[: -len(ending)] + card["search_line"]
    return item


def _steps_of_path(
    paths: dict[str, Any],
    key: str,
    *,
    case_id: str,
    session: Session,
    settings: Any,
    spent: bool,
) -> list[dict[str, Any]]:
    """Return the steps of one path, including its story intro."""
    chosen = dict(paths.get(key) or {})
    title = str(chosen.get("title", ""))
    return [
        _present_step(
            step,
            key=key,
            title=title,
            case_id=case_id,
            session=session,
            settings=settings,
            spent=spent,
        )
        for step in (chosen.get("steps") or [])
    ]


def _bridge(previous: dict[str, Any], next_key: str) -> dict[str, Any]:
    """Return the one line between two tracks, still on the screen just left.

    The bridge names no persona, so the tour does not send the current person
    to a screen they cannot open.  The next story intro switches persona.
    """
    title, caption = _BRIDGE_COPY[next_key]
    return {
        "id": f"bridge-{next_key}",
        "kind": "bridge",
        "title": title,
        "caption": caption,
        "persona": "",
        "actor_id": "",
        "permission": "",
        "target": "",
        "path": previous["path"],
        "path_key": next_key,
        "path_title": title,
        "muse": False,
        "replay_note": "",
    }


def _story_steps(
    paths: dict[str, Any],
    *,
    case_id: str,
    session: Session,
    settings: Any,
    spent: bool,
) -> list[dict[str, Any]]:
    """Return the three tracks in order, with one line between them."""
    combined: list[dict[str, Any]] = []
    for key in _story_keys():
        block = _steps_of_path(
            paths,
            key,
            case_id=case_id,
            session=session,
            settings=settings,
            spent=spent,
        )
        if combined:
            combined.append(_bridge(combined[-1], key))
        combined.extend(block)
    return combined


def _path_catalog(paths: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the path list the panel may offer, in the order of the file."""
    return [
        {
            "key": name,
            "title": str(value.get("title", "")),
            "minutes": int(value.get("minutes", 0) or 0),
        }
        for name, value in paths.items()
    ]


@router.get("/tour/steps", operation_id="ui_tour_steps")
def tour_step_list(
    request: Request,
    path: str = "",
    session: Session = Depends(get_session, scope="function"),
) -> Any:
    """Return one path, or the three tracks when no path is named.

    The list is read-only.  The browser switches persona through the ordinary
    persona switch and opens the screens the steps name.  An empty name, and
    the name story, walk the fence, then the café, then the city.  A name that
    is not a path still opens the café path.
    """
    payload = tour_steps()
    paths = dict(payload.get("paths") or {})
    named = str(payload.get("default_path") or "")
    settings = request.app.state.settings
    case_id = judge.copy_case_id(request) or guide_views.DEFAULT_CASE_ID
    spent = _allowance_spent(session, settings)
    catalog = _path_catalog(paths)
    title = str(payload.get("title", "Take the tour"))
    if path in {"", "story"}:
        return {
            "title": title,
            "path": "story",
            "paths": catalog,
            "steps": _story_steps(
                paths,
                case_id=case_id,
                session=session,
                settings=settings,
                spent=spent,
            ),
        }
    key = path if path in paths else (named if named in paths else next(iter(paths), ""))
    return {
        "title": title,
        "path": key,
        "paths": catalog,
        "steps": _steps_of_path(
            paths,
            key,
            case_id=case_id,
            session=session,
            settings=settings,
            spent=spent,
        ),
    }


__all__ = ["router", "tour_steps"]
