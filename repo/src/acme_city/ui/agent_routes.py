"""The routes and interface actions of the Agent Operator lane.

``ui/router.py`` includes ``router`` and merges ``ACTIONS`` into
``ACTION_HANDLERS``, so the lane adds its screens and its governed actions
here and never in the router body.  The screens are the operational home, the
run history and the operational summary of one case.
"""
# REQUIRES: UX-01

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.ui.router import ActionContext, Outcome, _guard, page_context, render, ui_actor
from acme_city.agents.summary import operator_summary
from acme_city.ui.agent_views import agent_case, run_history

router = APIRouter(tags=["agents"])

#: The interface actions of the lane, keyed by their stable identifier.
ACTIONS: dict[str, Callable[[ActionContext], Outcome]] = {}


def _role_permissions(ctx: ActionContext) -> Outcome:
    """Save the optional City worker entitlement through the governed service."""
    from acme_city.configuration.service import ConfigurationService

    enabled = ctx.text("city_worker_enabled").lower() in {"1", "true", "yes", "on"}
    reason = ctx.text("reason")
    service = ConfigurationService(ctx.session)
    for role_id in ("permit_reviewer", "intake_clerk"):
        service.set_agent_role_entitlement(
            role_id=role_id, can_run_agents=enabled, reason=reason, actor=ctx.actor
        )
    return Outcome(
        message="City worker agent access was saved.", destination="Users and roles",
        state="enabled" if enabled else "disabled", target_type="agent_role_entitlement",
        target_id="city_worker",
    )


ACTIONS["admin.role.permissions"] = _role_permissions


@router.get("/agents", operation_id="ui_agents_home")
def agents_home(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
):
    """Show the Agent Operator's stored operational summary."""
    resolved, refused = _guard(request, session, actor, "agents_home")
    if refused is not None:
        return refused
    context = page_context(
        request, session, resolved, screen="agents_home", title="Agents",
        summary=operator_summary(session),
    )
    return render(request, "agents.html", context)


@router.get("/agents/runs", operation_id="ui_agent_runs")
def agent_runs(
    request: Request,
    agent_key: str = "",
    state: str = "",
    engine: str = "",
    day: str = "",
    page: int = 1,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
):
    """Show one page of the recorded runs of the agents."""
    resolved, refused = _guard(request, session, actor, "agent_runs")
    if refused is not None:
        return refused
    view = run_history(
        session,
        resolved,
        agent_key=agent_key,
        state=state,
        engine=engine,
        day=day,
        page=page,
    )
    context = page_context(
        request, session, resolved, screen="agent_runs", title="Run history",
        view=view, summary=operator_summary(session),
    )
    return render(request, "agent_runs.html", context)


@router.get("/agents/cases/{application_id}", operation_id="ui_agent_case")
def agent_case_screen(
    request: Request,
    application_id: str,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
):
    """Show the operational summary of one case."""
    resolved, refused = _guard(request, session, actor, "agent_case")
    if refused is not None:
        return refused
    view = agent_case(session, resolved, application_id)
    context = page_context(
        request, session, resolved, screen="agent_case", title="Case summary",
        view=view, summary=operator_summary(session),
    )
    if view.get("missing"):
        return render(request, "agent_case.html", context, status_code=404)
    return render(request, "agent_case.html", context)


__all__ = ["ACTIONS", "router"]
