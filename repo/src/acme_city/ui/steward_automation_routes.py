"""The routes and interface actions of the steward automation lane.

``ui/router.py`` includes ``router`` and merges ``HANDLERS`` into
``ACTION_HANDLERS``, so the lane adds its screens and its governed actions
here and never in the router body.

Routes:

* ``GET /steward/automation``    the automatic linking settings

The two writes go through the UI dispatcher (``POST /ui/actions/{id}``), so
each one checks the CSRF token, the grant of the Data Steward, the reason and
the version of the policy the screen showed:

* ``registry.automation.activate``
* ``registry.automation.pause``
"""
# REQUIRES: UX-01, UX-02, SEC-01
# The screen is opened by the preview grant of the Data Steward, and the two
# writes are the grants that activate and pause the policy.

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.registry import automation
from acme_city.ui import steward_automation_views, steward_guide
from acme_city.ui.router import (
    ActionContext,
    Outcome,
    _guard,
    page_context,
    render,
    ui_actor,
)

router = APIRouter(tags=["steward"])

def _guide(state: dict[str, Any]) -> Any:
    """Build the saved guidance of the screen from the state it shows."""
    policy = state["policy"]
    evidence = (
        (f"policy version {policy['version']}", f"mode {policy['mode_label']}")
        if policy is not None
        else ("no policy is active",)
    )
    return steward_guide.build(
        steward_guide.GuideContext(
            screen="automation_settings",
            state=state["status"],
            evidence=evidence,
        )
    )
@router.get("/steward/automation", operation_id="ui_steward_automation")
def ui_steward_automation(
    request: Request,
    preview: str = "",
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the automatic linking settings of the Data Steward.

    The page reports the mode the automation really runs in, the thresholds of
    the policy and the controls that change it.  The preview reads the
    recorded scores of the accepted source records; it changes nothing.
    """
    resolved, refused = _guard(request, session, actor, "steward_automation")
    if refused is not None:
        return refused
    policy = automation.active_policy(session)
    state = steward_automation_views.state(
        session,
        resolved,
        policy=policy,
        deployment_mode=request.app.state.settings.registry_automation_mode,
    )
    preview_view = None
    if preview:
        preview_view = steward_automation_views.preview(
            session,
            policy=policy,
            scope=state["scope"] or [item["key"] for item in state["datasets"]],
        )
    context = page_context(
        request,
        session,
        resolved,
        screen="steward_automation",
        title="Automatic linking",
        automation=state,
        preview=preview_view,
        guide=_guide(state),
        quiet_feedback=True,
    )
    return render(request, "steward_automation.html", context)


def _automation_activate(ctx: ActionContext) -> Outcome:
    """Activate a policy version for the automatic linking."""
    policy = automation.activate_policy(
        ctx.session,
        ctx.actor,
        mode=ctx.text("mode"),
        source_scopes=ctx.values("source_scope"),
        reason=ctx.text("reason"),
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message=(
            f"Policy version {policy.version} is active. It covers "
            f"{len(policy.source_scopes)} source dataset"
            f"{'' if len(policy.source_scopes) == 1 else 's'}."
        ),
        destination="Automatic linking policy",
        state=policy.mode,
        target_type="registry_automation_policy",
        target_id=policy.id,
        after_version=policy.version,
    )


def _automation_pause(ctx: ActionContext) -> Outcome:
    """Pause the automatic linking with a new policy version."""
    policy = automation.pause_policy(
        ctx.session,
        ctx.actor,
        reason=ctx.text("reason"),
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message=f"Policy version {policy.version} pauses the automatic linking.",
        destination="Automatic linking policy",
        state=policy.mode,
        target_type="registry_automation_policy",
        target_id=policy.id,
        after_version=policy.version,
    )


#: The interface actions of the lane, keyed by their stable identifier.
HANDLERS: dict[str, Callable[[ActionContext], Outcome]] = {
    "registry.automation.activate": _automation_activate,
    "registry.automation.pause": _automation_pause,
}

__all__ = ["HANDLERS", "router"]
