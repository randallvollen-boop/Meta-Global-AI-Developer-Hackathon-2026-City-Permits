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
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.core.errors import ValidationError
from acme_city.ui.router import ActionContext, Outcome, _guard, page_context, render, ui_actor
from acme_city.agents.summary import operator_summary
from acme_city.ui.agent_views import (
    agent_case,
    agent_screen,
    run_detail,
    run_history,
    run_progress,
)

router = APIRouter(tags=["agents"])

#: The interface actions of the lane, keyed by their stable identifier.
ACTIONS: dict[str, Callable[[ActionContext], Outcome]] = {}

#: The values a form field may hold for a true answer.
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _agent_processing(ctx: ActionContext) -> Outcome:
    """Save the processing policy of the City.

    The policy says when the agents work.  It never says what a case
    decides: the people of the City still review every recommendation.

    The daily allowance of provider calls is a setting of the deployment,
    not a setting of the City, so a request that tries to raise it is
    refused.  On a hosted demonstration the provider lock wins over any
    configuration.
    """
    from acme_city.configuration.service import ConfigurationService
    from acme_city.muse.client import live_call_block_reason

    cap = ctx.integer("muse_daily_call_cap")
    if cap is not None and cap > 0:
        blocked = live_call_block_reason(ctx.settings)
        if blocked is not None:
            raise ValidationError(
                "the live Muse calls of this deployment are locked, so the daily "
                "allowance stays at 0"
            )
        raise ValidationError(
            "the daily allowance of provider calls is a setting of the deployment, "
            "so it cannot be changed here"
        )
    runs_per_hour = ctx.integer("runs_per_hour")
    if runs_per_hour is None:
        raise ValidationError("the hourly limit of the agents is required")
    row = ConfigurationService(ctx.session).set_processing_policy(
        automatic=ctx.text("keep_awake").lower() in TRUE_VALUES,
        runs_per_hour=runs_per_hour,
        reason=ctx.text("reason"),
        actor=ctx.actor,
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message="The processing settings were saved.",
        destination="Agent processing",
        state=row.mode,
        target_type="agent_processing_policy",
        target_id=row.id,
        after_version=row.version,
    )


ACTIONS["admin.agent.processing"] = _agent_processing


def _agent_retry(ctx: ActionContext) -> Outcome:
    """Run the failed work of one case again.

    The retry is a manual run: the browser does not choose the agent, the
    agent is named by the work it repeats.  The failure is recorded on the
    queue row, so the operator sees what happened before trying again.
    """
    from acme_city.agents.control import AGENT_LABELS, AgentControlService
    from acme_city.agents.runtime import AgentRunFailed, retry_agent
    from acme_city.permits.service import PermitService

    application_id = ctx.text("application_id")
    agent_key = ctx.text("agent_key")
    # The grant is checked before the payload, so a request without the
    # grant is refused for that reason and nothing else.
    AgentControlService(ctx.session).authorize_manual_run(ctx.actor, agent_key)
    if not application_id:
        raise ValidationError("the retry needs the case it works on")
    label = AGENT_LABELS.get(agent_key, agent_key)
    application = PermitService(ctx.session).load_application(application_id)
    try:
        result = retry_agent(
            ctx.session,
            application=application,
            agent_key=agent_key,
            triggered_by=ctx.actor.actor_id,
            settings=ctx.settings,
        )
    except AgentRunFailed:
        return Outcome(
            message=(
                f"The {label.lower()} stopped again on {application_id}. The work "
                "waits for a person."
            ),
            destination=label,
            state="failed",
            target_type="application",
            target_id=application_id,
        )
    return Outcome(
        message=f"The {label.lower()} ran again on {application_id}.",
        destination=label,
        state=result.outcome,
        target_type="application",
        target_id=application_id,
        after_version=result.attempts,
    )


ACTIONS["agent.retry"] = _agent_retry


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
        # The cases waiting for the intake agent, as the Incoming list.
        inbox=agent_screen(session, resolved, "intake"),
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
        request, session, resolved, screen="agent_runs", title="Agent runs",
        view=view, summary=operator_summary(session),
    )
    return render(request, "agent_runs.html", context)


@router.get("/agents/runs/{run_id}", operation_id="ui_agent_run_detail")
def agent_run_detail(
    request: Request,
    run_id: str,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
):
    """Show the stored evidence for one agent attempt."""
    resolved, refused = _guard(request, session, actor, "agent_runs")
    if refused is not None:
        return refused
    view = run_detail(session, resolved, run_id)
    context = page_context(
        request, session, resolved, screen="agent_runs", title="Run detail",
        view=view, summary=operator_summary(session),
    )
    if view.get("missing"):
        return render(request, "agent_run_detail.html", context, status_code=404)
    return render(request, "agent_run_detail.html", context)


@router.get("/agents/runs/{run_id}/dag", operation_id="ui_agent_run_dag")
def agent_run_dag(
    request: Request,
    run_id: str,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
):
    """Return the step graph of one attempt, as the fragment the script reads.

    The fragment is the graph of the recorded run and nothing else: no state
    of the agent, no figure and no name of a person.  A persona that may not
    read the operations screens is refused, and an attempt that does not
    exist answers that it is not available.
    """
    from acme_city.ui.router import templates

    resolved, refused = _guard(request, session, actor, "agent_runs")
    if refused is not None:
        return refused
    progress = run_progress(session, run_id)
    if progress is None:
        return HTMLResponse(
            "This recorded run is not available.", status_code=404
        )
    module = templates.env.get_template("components/agent_dag.html").module
    return HTMLResponse(
        str(module.agent_dag(progress["levels"], progress["run_id"])),
        headers={"Cache-Control": "no-store"},
    )


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
