"""The view models of the two agent screens and of the administration screen.

The agent screens report what the database actually holds: the awake or
asleep state of the agent, the counts that were computed from the stored
runs and cases, the dependency graph, the waiting list and the run history.
The administration screen's view model lives in ``admin_config_views``.

Nothing here decides anything: every change is a governed action that the
server checks.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.agents import graphs
from acme_city.agents.control import AGENT_KEYS, AGENT_LABELS, AgentControlService
from acme_city.agents.intake import waiting_applications
from acme_city.auth.context import ActorContext
from acme_city.core.clock import utc_now
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import audit, permit

# The administration view model moved to ``admin_config_views``; it is
# re-exported so ``from acme_city.ui.agent_views import administration`` works.
from acme_city.ui.admin_config_views import administration

#: The screens the agents and the administration live on.
SCREEN_AGENT_INTAKE = "agent_intake"
SCREEN_AGENT_ADJUDICATION = "agent_adjudication"
SCREEN_ADMIN = "admin"

#: The status of an application that waits for the intake agent.
STATUS_SUBMITTED = "submitted"

#: The statuses a case may hold while it is in review.
IN_REVIEW_STATUSES: tuple[str, ...] = ("ready_for_review", "under_review")


def _iso(value) -> str:
    """Return a display-safe timestamp."""
    return value.isoformat() if value is not None else ""


def agent_state(session: Session, agent_key: str) -> dict[str, Any]:
    """Return the awake or asleep state of one agent."""
    service = AgentControlService(session)
    for row in service.snapshot():
        if row["agent_key"] == agent_key:
            return row
    return {
        "agent_key": agent_key,
        "label": AGENT_LABELS.get(agent_key, agent_key),
        "mode": agent_models.AGENT_ASLEEP,
        "version": 0,
        "changed_by": None,
        "changed_at": None,
    }


def _runs(session: Session, agent_key: str) -> list[agent_models.AgentRun]:
    """Return the recorded runs of one agent, newest first."""
    return list(
        session.execute(
            select(agent_models.AgentRun)
            .where(agent_models.AgentRun.agent_key == agent_key)
            .order_by(agent_models.AgentRun.started_at.desc(), agent_models.AgentRun.id.desc())
        ).scalars().all()
    )


def _run_nodes(session: Session, run_id: str) -> list[dict[str, Any]]:
    """Return the node trace of one run."""
    rows = session.execute(
        select(agent_models.AgentRunNode)
        .where(agent_models.AgentRunNode.agent_run_id == run_id)
        .order_by(agent_models.AgentRunNode.position)
    ).scalars().all()
    return [
        {
            "node_id": row.node_id,
            "label": row.label,
            "level": row.dependency_level,
            "status": row.status,
            "note": row.note or "",
        }
        for row in rows
    ]


def _pending_recommendations(session: Session) -> list[permit.Recommendation]:
    """Return the pending recommendations of every case."""
    return list(
        session.execute(
            select(permit.Recommendation)
            .where(permit.Recommendation.status == "pending")
            .order_by(permit.Recommendation.created_at.desc())
        ).scalars().all()
    )


def agent_screen(
    session: Session, actor: ActorContext, agent_key: str
) -> dict[str, Any]:
    """Return the view model of one agent screen.

    The counts are computed from the stored cases and the stored runs; none of
    them is estimated.
    """
    state = agent_state(session, agent_key)
    runs = _runs(session, agent_key)
    nodes_by_run = {run.id: _run_nodes(session, run.id) for run in runs}
    pending = _pending_recommendations(session)

    applications = list(
        session.execute(
            select(permit.Application).order_by(permit.Application.source_application_number)
        ).scalars().all()
    )
    submitted = waiting_applications(session)
    needs_information = [
        row
        for row in applications
        if row.status == "needs_information" and row.scenario_id is None
    ]
    in_review = [row for row in applications if row.status in IN_REVIEW_STATUSES]
    pending_ids = {row.application_id for row in pending}
    awaiting = [
        row for row in in_review if row.id not in pending_ids
    ]

    if agent_key == "intake":
        waiting = submitted
        kpis = [
            {"label": "Waiting", "value": len(submitted), "testid": "kpi-waiting"},
            {
                "label": "Processed",
                "value": len([run for run in runs if run.outcome in {"completed", "needs_information"}]),
                "testid": "kpi-processed",
            },
            {
                "label": "Needs human",
                "value": len(needs_information),
                "testid": "kpi-needs-human",
            },
            {
                "label": "Errors",
                "value": len([run for run in runs if run.outcome == "failed"]),
                "testid": "kpi-errors",
            },
        ]
    else:
        waiting = awaiting
        kpis = [
            {"label": "In review", "value": len(in_review), "testid": "kpi-in-review"},
            {"label": "Recommended", "value": len(pending), "testid": "kpi-recommended"},
            {
                "label": "Awaiting confirmation",
                "value": len([row for row in pending if row.proposed_outcome != "hold"]),
                "testid": "kpi-awaiting-confirmation",
            },
            {
                "label": "Held for a person",
                "value": len([row for row in pending if row.proposed_outcome == "hold"]),
                "testid": "kpi-held",
            },
        ]

    waiting_rows = [
        {
            "application_id": row.id,
            "source_application_number": row.source_application_number,
            "status": row.status,
            "permit_type_key": _type_key(session, row.permit_type_id),
            "review_area": row.review_area or "",
            "version": row.version,
        }
        for row in waiting
    ]
    awaiting_rows = [
        {
            "application_id": row.application_id,
            "source_application_number": _number_of(session, row.application_id),
            "proposed_outcome": row.proposed_outcome,
            "rationale": row.rationale or "",
            "conditions": list(row.conditions or []),
            "recommendation_id": row.id,
            "created_at": _iso(row.created_at),
        }
        for row in pending
    ]
    history = [
        {
            "run_id": run.id,
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
            "reference": _number_of(session, run.application_id) if run.application_id else "",
            "result": run.outcome,
            "detail": run.outcome_detail or "",
            "target": run.application_id or "",
            "triggered_by": run.triggered_by or "",
            "nodes": nodes_by_run.get(run.id, []),
        }
        for run in runs
    ]

    return {
        "agent_key": agent_key,
        "agent_label": AGENT_LABELS.get(agent_key, agent_key),
        "state": state,
        "is_awake": state["mode"] == agent_models.AGENT_AWAKE,
        "can_toggle": _holds(session, actor, "agent.toggle"),
        "can_run": _holds(session, actor, f"agent.run.{agent_key}"),
        "kpis": kpis,
        "graph": _graph_view(agent_key),
        "waiting": waiting_rows,
        "awaiting": awaiting_rows,
        "history": history,
        "evidence": [
            {
                "label": f"{run['reference'] or 'run'} · {run['result']}",
                "kind": "agent run",
                "detail": run["run_id"],
                "received_at": run["started_at"],
            }
            for run in history
        ],
        "model_runs": [],
        "audit_history": _agent_history(session, agent_key),
    }


def _agent_history(session: Session, agent_key: str) -> list[dict[str, Any]]:
    """Return the recorded audit entries of one agent."""
    rows = session.execute(
        select(audit.AuditEvent)
        .where(audit.AuditEvent.action.like("agent.%"))
        .order_by(audit.AuditEvent.occurred_at.desc())
        .limit(50)
    ).scalars().all()
    entries: list[dict[str, Any]] = []
    for row in rows:
        metadata = dict(row.metadata_json or {})
        if metadata.get("agent") not in (None, agent_key):
            continue
        entries.append(
            {
                "event_id": row.id,
                "occurred_at": _iso(row.occurred_at),
                "actor_id": row.actor_id or "",
                "actor_label": _actor_label(session, row.actor_id),
                "action": row.action,
                "outcome": row.outcome,
                "before_version": row.before_version,
                "after_version": row.after_version,
                "reason": row.reason or "",
                "references": list(row.references or []),
                "denial_reason": row.denial_reason or "",
            }
        )
    return entries


def _actor_label(session: Session, actor_id: str | None) -> str:
    """Return the display label of one actor."""
    from acme_city.ui.view_models import actor_label

    return actor_label(session, actor_id)


def _number_of(session: Session, application_id: str | None) -> str:
    """Return the source application number of one application."""
    if not application_id:
        return ""
    row = session.get(permit.Application, application_id)
    return "" if row is None else row.source_application_number


def _type_key(session: Session, permit_type_id: str | None) -> str:
    """Return the catalogue key of one permit type."""
    if not permit_type_id:
        return ""
    row = session.get(permit.PermitType, permit_type_id)
    return "" if row is None else row.key


def _holds(session: Session, actor: ActorContext, permission: str) -> bool:
    """Return whether the actor holds one grant."""
    from acme_city.auth.permissions import PermissionResolver

    return any(
        grant.action == permission
        for grant in PermissionResolver(session).grants_for(actor.actor_id)
    )


def _graph_view(agent_key: str) -> list[list[dict[str, Any]]]:
    """Return the dependency graph of one agent, grouped into levels."""
    levels: list[list[dict[str, Any]]] = []
    for level in graphs.levels_of(agent_key):
        levels.append(
            [
                {
                    "node_id": node.node_id,
                    "label": node.label,
                    "description": node.description,
                }
                for node in level
            ]
        )
    return levels


def sidebar_status(session: Session, actor: ActorContext) -> dict[str, Any] | None:
    """Return the agent status line for the sidebar.

    The line is shown to staff only: an applicant never sees it.
    """
    if not (
        _holds(session, actor, "agent.run.intake")
        or _holds(session, actor, "agent.run.adjudication")
    ):
        return None
    state = agent_state(session, "intake")
    waiting = len(waiting_applications(session))
    return {
        "agent_key": "intake",
        "mode": state["mode"],
        "mode_label": "awake" if state["mode"] == agent_models.AGENT_AWAKE else "asleep",
        "waiting": waiting,
        "text": (
            f"Intake agent is {state['mode']} · {waiting} awaiting processing"
        ),
    }


__all__ = [
    "IN_REVIEW_STATUSES",
    "SCREEN_ADMIN",
    "SCREEN_AGENT_ADJUDICATION",
    "SCREEN_AGENT_INTAKE",
    "STATUS_SUBMITTED",
    "administration",
    "agent_screen",
    "agent_state",
    "sidebar_status",
]
