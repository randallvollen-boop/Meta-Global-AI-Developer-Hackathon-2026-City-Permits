"""The view models of the two agent screens and of the administration screen.

The agent screens report what the database actually holds: the awake or
asleep state of the agent, the counts that were computed from the stored
runs and cases, the dependency graph, the waiting list and the run history.
The administration screen reports the permit-type configuration, the people
and the service identities, the reason codes and the configuration log.

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
from acme_city.persistence.models import audit, governance, permit

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


# ------------------------------------------------------------------ administration


def _permit_type_rows(session: Session) -> list[permit.PermitType]:
    """Return every permit type, in catalogue order."""
    return list(
        session.execute(
            select(permit.PermitType).order_by(permit.PermitType.label)
        ).scalars().all()
    )


def administration(session: Session, actor: ActorContext) -> dict[str, Any]:
    """Return the view model of the administration screen."""
    types = _permit_type_rows(session)
    known_documents: set[str] = set()
    for row in types:
        known_documents.update(row.required_documents or [])
    type_rows = [
        {
            "permit_type_id": row.id,
            "permit_type_key": row.key,
            "label": row.label,
            "description": row.description or "",
            "review_area": row.review_area or row.review_route,
            "process_category": row.process_category or "",
            "discretionary": bool(row.discretionary),
            "required_fields": list(row.required_fields or []),
            "required_documents": list(row.required_documents or []),
            "fee_schedule_key": row.fee_schedule_key or "",
            "version": row.version,
            "active": row.active,
        }
        for row in types
    ]
    people = _people(session)
    service_identities = _service_identities(session)
    reason_codes = _reason_codes(session)
    log = _configuration_log(session)
    from acme_city.ui.view_models import permit_type_icons

    return {
        "permit_types": type_rows,
        "known_documents": sorted(known_documents),
        "process_categories": ["simple", "with_plans", "formal_review"],
        "review_areas": sorted(
            {row["review_area"] for row in type_rows if row["review_area"]}
        ),
        "people": people,
        "service_identities": service_identities,
        "reason_codes": reason_codes,
        "configuration_log": log,
        "permit_type_icons": permit_type_icons(session, actor),
        "fee_schedules": _fee_schedules(session),
        "evidence": [
            {
                "label": entry["action"],
                "kind": "configuration change",
                "detail": entry["target_id"],
                "received_at": entry["occurred_at"],
            }
            for entry in log
        ],
        "model_runs": [],
        "audit_history": [
            {
                "event_id": entry["audit_event_id"],
                "occurred_at": entry["occurred_at"],
                "actor_id": entry["actor"],
                "actor_label": _actor_label(session, entry["actor"]),
                "action": entry["action"],
                "outcome": "accepted",
                "before_version": None,
                "after_version": None,
                "reason": entry["reason"],
                "references": [],
                "denial_reason": "",
            }
            for entry in log
        ],
        "can_manage": _holds(session, actor, "config.manage"),
        "can_manage_users": _holds(session, actor, "admin.actor.manage"),
        "can_manage_icons": _holds(session, actor, "permit.icon.generate"),
    }


def _fee_schedules(session: Session) -> list[dict[str, Any]]:
    """Return the published fee schedules the administrator may choose."""
    from acme_city.persistence.models import finance

    rows = session.execute(
        select(finance.FeeScheduleVersion)
        .where(finance.FeeScheduleVersion.status == "published")
        .order_by(finance.FeeScheduleVersion.fee_schedule_id)
    ).scalars().all()
    return [
        {
            "fee_schedule_id": row.fee_schedule_id,
            "version_label": row.version_label,
            "currency": row.currency,
        }
        for row in rows
    ]


def _people(session: Session) -> list[dict[str, Any]]:
    """Return the people of the demonstration and the users added later."""
    rows = session.execute(
        select(governance.Actor).order_by(governance.Actor.label)
    ).scalars().all()
    people: list[dict[str, Any]] = []
    for row in rows:
        if row.selectable or row.actor_id.startswith("persona_") or row.persona_role:
            people.append(
                {
                    "actor_id": row.actor_id,
                    "label": row.label,
                    "role_label": row.persona_role or _persona_label(row.actor_id),
                    "department": row.department or "",
                    "selectable": bool(row.selectable),
                }
            )
    return people


def _persona_label(actor_id: str) -> str:
    """Return the persona label of one seeded persona."""
    return {
        "persona_applicant": "Applicant",
        "persona_data_steward": "Data Steward",
        "persona_permit_reviewer": "Permit Reviewer",
        "persona_city_administrator": "City Administrator",
    }.get(actor_id, actor_id)


def _service_identities(session: Session) -> list[dict[str, Any]]:
    """Return the service identities, including the two agents."""
    rows = session.execute(
        select(governance.Actor)
        .where(governance.Actor.selectable.is_(False))
        .order_by(governance.Actor.label)
    ).scalars().all()
    identities: list[dict[str, Any]] = []
    for row in rows:
        identities.append(
            {
                "actor_id": row.actor_id,
                "label": row.label,
                "is_agent": row.actor_id in ("service_agent_intake", "service_agent_adjudication"),
            }
        )
    return identities


def _reason_codes(session: Session) -> list[dict[str, Any]]:
    """Return the reason codes of the City."""
    rows = session.execute(
        select(permit.ReasonCode).order_by(permit.ReasonCode.code)
    ).scalars().all()
    return [
        {
            "code": row.code,
            "label": row.label,
            "description": row.description or "",
            "active": bool(row.active),
            "version": row.version,
        }
        for row in rows
    ]


def _configuration_log(session: Session) -> list[dict[str, Any]]:
    """Return the configuration audit entries, newest first."""
    rows = session.execute(
        select(audit.AuditEvent)
        .where(
            audit.AuditEvent.target_type.in_(
                [
                    "permit_type",
                    "reason_code",
                    "actor",
                    "agent_control",
                    "configuration",
                ]
            )
        )
        .order_by(audit.AuditEvent.occurred_at.desc(), audit.AuditEvent.id.desc())
        .limit(50)
    ).scalars().all()
    entries: list[dict[str, Any]] = []
    for row in rows:
        metadata = dict(row.metadata_json or {})
        entries.append(
            {
                "audit_event_id": row.id,
                "occurred_at": _iso(row.occurred_at),
                "action": row.action,
                "target_type": row.target_type or "",
                "target_id": row.target_id or "",
                "actor": row.actor_id or "",
                "reason": row.reason or "",
                "before": metadata.get("before", ""),
                "after": metadata.get("after", ""),
            }
        )
    return entries


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
