"""The view models of the two agent screens and of the administration screen.

The agent screens report what the database actually holds: the awake or
asleep state of the agent, the counts that were computed from the stored
runs and cases, the dependency graph, the waiting list and the run history.
The administration screen's view model lives in ``admin_config_views``.

Nothing here decides anything: every change is a governed action that the
server checks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.agents import graphs
from acme_city.agents.control import AGENT_KEYS, AGENT_LABELS, AgentControlService
from acme_city.agents.intake import waiting_applications
from acme_city.agents.runtime import (
    BUILTIN_ENGINE,
    BUILTIN_ENGINE_LABEL,
    DEFAULT_MAX_BATCH_SIZE,
    DEFAULT_RUNS_PER_HOUR,
    batch_limit,
    retry_allowed,
)
from acme_city.auth.context import ActorContext
from acme_city.core.clock import utc_now
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import agent_ops, audit, model_run as model_run_models, permit

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

#: The number of runs one page of the history shows.
RUN_PAGE_SIZE = 25

#: The number of recent results the agent screen shows.
RECENT_RESULT_COUNT = 20

#: What a recorded state of a run means for the operator.
RUN_STATE_LABELS: dict[str, str] = {
    "completed": "Completed",
    "needs_information": "Needs information",
    "recommended": "Recommended",
    "held": "Waiting for a person",
    "failed": "Failed",
    "skipped": "Skipped",
    "recorded": "Recorded",
}

#: The engines a recorded run may name.
ENGINE_LABELS: dict[str, str] = {BUILTIN_ENGINE: BUILTIN_ENGINE_LABEL}


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
    in_review = [
        row
        for row in applications
        if row.status in IN_REVIEW_STATUSES and row.scenario_id is None
    ]
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
    queue_rows = _queue_rows(session, agent_key)
    failures = [
        _queue_row_view(session, row) for row in queue_rows if row.status == agent_ops.WORK_FAILED
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
            "triggered_label": _actor_label(session, run.triggered_by),
            "duration": _duration(run),
            "engine_label": ENGINE_LABELS.get(_engine_of(run), _engine_of(run)),
            "nodes": nodes_by_run.get(run.id, []),
        }
        for run in runs[:RECENT_RESULT_COUNT]
    ]

    return {
        "agent_key": agent_key,
        "agent_label": AGENT_LABELS.get(agent_key, agent_key),
        "state": state,
        "is_awake": state["mode"] == agent_models.AGENT_AWAKE,
        "can_toggle": _holds(session, actor, "agent.toggle"),
        "can_run": _holds(session, actor, f"agent.run.{agent_key}"),
        # The most cases one manual batch may name, so the button on the
        # screen says what it will do.
        "batch_limit": batch_limit(session).max_batch_size,
        # The processing policy of the City and the engine that produces the
        # runs.  They are separate things: the policy says when work starts,
        # the engine says what produces it.
        "policy": _policy_view(session),
        "engine": BUILTIN_ENGINE_LABEL,
        "kpis": kpis,
        "graph": _graph_view(agent_key),
        "waiting": waiting_rows,
        "failures": failures,
        "awaiting": awaiting_rows,
        "history": history,
        "history_total": len(runs),
        "evidence": [
            {
                "label": f"{run['reference'] or 'run'} · {run['result']}",
                "kind": "agent run",
                "detail": run["run_id"],
                "received_at": run["started_at"],
            }
            for run in history
        ],
        "model_runs": _linked_model_runs(session, runs),
        "audit_history": _agent_history(session, agent_key),
    }


def _policy_view(session: Session) -> dict[str, Any]:
    """Return the processing policy of the City, as the screens show it."""
    from acme_city.agents.policy import MODE_MANUAL, current_policy, processing_label

    policy = current_policy(session)
    mode = policy.mode if policy is not None else MODE_MANUAL
    return {
        "mode": mode,
        "label": processing_label(mode),
        "runs_per_hour": policy.runs_per_hour if policy is not None else DEFAULT_RUNS_PER_HOUR,
        "max_batch_size": (
            policy.max_batch_size if policy is not None else DEFAULT_MAX_BATCH_SIZE
        ),
    }


def _queue_rows(session: Session, agent_key: str) -> list[agent_ops.AgentWorkQueue]:
    """Return the queued work of one agent, newest first."""
    return list(
        session.execute(
            select(agent_ops.AgentWorkQueue)
            .where(agent_ops.AgentWorkQueue.agent_key == agent_key)
            .order_by(agent_ops.AgentWorkQueue.created_at.desc())
        ).scalars().all()
    )


def _queue_row_view(session: Session, row: agent_ops.AgentWorkQueue) -> dict[str, Any]:
    """Return what the operator needs to know about one piece of queued work."""
    return {
        "work_id": row.id,
        "application_id": row.application_id,
        "reference": _number_of(session, row.application_id),
        "status": row.status,
        "attempts": row.attempts,
        "note": row.note or "",
        "finished_at": _iso(row.finished_at),
        # A technical failure may be tried again by a person.  A work that
        # waits for a person is never retried.
        "can_retry": retry_allowed(row),
    }


def _linked_model_runs(
    session: Session, runs: list[agent_models.AgentRun]
) -> list[dict[str, Any]]:
    """Return the model runs the recorded runs of the agent produced.

    A built in run names the agent run it belongs to, so the operator reads
    the evidence of the attempt next to the attempt itself.
    """
    from acme_city.ui.view_models import muse_source_label

    run_ids = {run.id for run in runs}
    if not run_ids:
        return []
    rows = session.execute(
        select(model_run_models.ModelRun).order_by(model_run_models.ModelRun.started_at.desc())
    ).scalars().all()
    views: list[dict[str, Any]] = []
    for row in rows:
        refs = row.input_refs or {}
        agent_run_id = refs.get("agent_run_id") if isinstance(refs, dict) else None
        if agent_run_id not in run_ids:
            continue
        validation = dict(row.validation_result or {})
        views.append(
            {
                "run_id": row.id,
                "mode": row.mode,
                "mode_label": row.mode.capitalize(),
                "source_label": muse_source_label(row.model, row.mode),
                "status": row.status,
                "provider": row.provider,
                "model": row.model,
                "response_id": row.provider_response_id,
                "latency_ms": row.latency_ms,
                "error": row.error,
                "replay_of_run_id": row.replay_of_run_id,
                "validation_errors": list(validation.get("errors") or []),
                "usage": dict(row.usage or {}),
                "started_at": _iso(row.started_at),
                "completed_at": _iso(row.completed_at),
            }
        )
    return views


def _duration(run: agent_models.AgentRun) -> str:
    """Return how long the run took, in the words of the operator."""
    if run.finished_at is None:
        return ""
    seconds = int((run.finished_at - run.started_at).total_seconds())
    if seconds < 60:
        return f"{seconds} s"
    return f"{seconds // 60} min {seconds % 60} s"


def _engine_of(run: agent_models.AgentRun) -> str:
    """Return the engine the run names."""
    inputs = run.inputs or {}
    engine = str(inputs.get("engine") or "") if isinstance(inputs, dict) else ""
    return engine or BUILTIN_ENGINE


def run_history(
    session: Session,
    actor: ActorContext,
    *,
    agent_key: str = "",
    state: str = "",
    engine: str = "",
    day: str = "",
    page: int = 1,
) -> dict[str, Any]:
    """Return one page of the recorded runs, newest first.

    The filters are the agent, the state, the engine and the day of the run.
    Every figure is the one the database holds; none of them is estimated.
    """
    statement = select(agent_models.AgentRun)
    wanted_agent = agent_key if agent_key in AGENT_KEYS else ""
    if wanted_agent:
        statement = statement.where(agent_models.AgentRun.agent_key == wanted_agent)
    wanted_state = state if state in RUN_STATE_LABELS else ""
    if wanted_state:
        statement = statement.where(agent_models.AgentRun.outcome == wanted_state)
    wanted_engine = engine if engine in ENGINE_LABELS else ""
    if wanted_engine:
        statement = statement.where(
            agent_models.AgentRun.inputs["engine"].as_string() == wanted_engine
        )
    wanted_day = ""
    if day:
        try:
            start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            start = None
        if start is not None:
            wanted_day = day
            statement = statement.where(
                agent_models.AgentRun.started_at >= start,
                agent_models.AgentRun.started_at < start + timedelta(days=1),
            )
    total = int(
        session.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        or 0
    )
    pages = max((total + RUN_PAGE_SIZE - 1) // RUN_PAGE_SIZE, 1)
    current = min(max(int(page or 1), 1), pages)
    runs = list(
        session.execute(
            statement.order_by(
                agent_models.AgentRun.started_at.desc(), agent_models.AgentRun.id.desc()
            )
            .limit(RUN_PAGE_SIZE)
            .offset((current - 1) * RUN_PAGE_SIZE)
        ).scalars().all()
    )
    rows = [
        {
            "run_id": run.id,
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
            "application_id": run.application_id or "",
            "reference": _number_of(session, run.application_id),
            "agent_key": run.agent_key,
            "agent_label": AGENT_LABELS.get(run.agent_key, run.agent_key),
            "state": run.outcome,
            "state_label": RUN_STATE_LABELS.get(run.outcome, run.outcome),
            "engine": _engine_of(run),
            "engine_label": ENGINE_LABELS.get(_engine_of(run), _engine_of(run)),
            "triggered_by": run.triggered_by or "",
            "triggered_label": _actor_label(session, run.triggered_by),
            "duration": _duration(run),
        }
        for run in runs
    ]
    query = urlencode(
        {
            name: value
            for name, value in (
                ("agent_key", wanted_agent),
                ("state", wanted_state),
                ("engine", wanted_engine),
                ("day", wanted_day),
            )
            if value
        }
    )
    return {
        "rows": rows,
        "total": total,
        "page": current,
        "pages": pages,
        "page_size": RUN_PAGE_SIZE,
        "filters": {
            "agent_key": wanted_agent,
            "state": wanted_state,
            "engine": wanted_engine,
            "day": wanted_day,
        },
        "query": query,
        "agents": [
            {"key": key, "label": AGENT_LABELS.get(key, key)} for key in AGENT_KEYS
        ],
        "states": [
            {"key": key, "label": label} for key, label in RUN_STATE_LABELS.items()
        ],
        "engines": [
            {"key": key, "label": label} for key, label in ENGINE_LABELS.items()
        ],
    }


def run_detail(session: Session, actor: ActorContext, run_id: str) -> dict[str, Any]:
    """Return the stored evidence and guarded retry state of one attempt."""
    run = session.get(agent_models.AgentRun, run_id)
    if run is None:
        work = session.get(agent_ops.AgentWorkQueue, run_id)
        if work is None:
            return {"missing": True, "run_id": run_id}
        return _failed_work_detail(session, actor, work)

    application = session.get(permit.Application, run.application_id) if run.application_id else None
    inputs = dict(run.inputs or {})
    runs: list[agent_models.AgentRun] = []
    if run.application_id:
        runs = list(
            session.execute(
                select(agent_models.AgentRun)
                .where(
                    agent_models.AgentRun.application_id == run.application_id,
                    agent_models.AgentRun.agent_key == run.agent_key,
                )
                .order_by(agent_models.AgentRun.started_at, agent_models.AgentRun.id)
            ).scalars().all()
        )
    position = next((index for index, row in enumerate(runs) if row.id == run.id), -1)
    previous = runs[position - 1] if position > 0 else None
    subsequent = runs[position + 1] if position >= 0 and position + 1 < len(runs) else None
    work = None
    if run.application_id:
        work = session.execute(
            select(agent_ops.AgentWorkQueue)
            .where(
                agent_ops.AgentWorkQueue.application_id == run.application_id,
                agent_ops.AgentWorkQueue.agent_key == run.agent_key,
            )
            .order_by(agent_ops.AgentWorkQueue.created_at.desc())
        ).scalars().first()
    recorded_revision = inputs.get("revision")
    current_revision = application.revision if application is not None else None
    current_revision_matches = (
        recorded_revision is None
        or current_revision is None
        or recorded_revision == current_revision
    )
    retryable = (
        run.outcome == "failed"
        and work is not None
        and retry_allowed(work)
        and current_revision_matches
    )
    findings = []
    if run.application_id:
        findings = list(
            session.execute(
                select(permit.ApplicationFinding)
                .where(permit.ApplicationFinding.agent_run_id == run.id)
                .order_by(permit.ApplicationFinding.created_at)
            ).scalars().all()
        )
    model_runs = _linked_model_runs(session, [run])
    return {
        "missing": False,
        "run_id": run.id,
        "agent_key": run.agent_key,
        "agent_label": AGENT_LABELS.get(run.agent_key, run.agent_key),
        "application_id": run.application_id or "",
        "reference": _number_of(session, run.application_id),
        "recorded_revision": recorded_revision if recorded_revision is not None else "Not recorded",
        "current_revision": current_revision if current_revision is not None else "Not available",
        "revision_matches": current_revision_matches,
        "triggered_by": _actor_label(session, run.triggered_by) or "Automatic policy",
        "service_identity": _actor_label(session, run.service_identity_id) or run.service_identity_id,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at) or "Still running",
        "duration": _duration(run) or "Still running",
        "state": run.outcome,
        "state_label": RUN_STATE_LABELS.get(run.outcome, run.outcome),
        "detail": run.outcome_detail or "No additional detail was recorded.",
        "engine_label": ENGINE_LABELS.get(_engine_of(run), _engine_of(run)),
        "nodes": _run_nodes(session, run.id),
        "model_runs": model_runs,
        "findings": [
            {
                "type": finding.finding_type,
                "message": finding.message,
                "severity": finding.severity,
            }
            for finding in findings
        ],
        "previous": _run_link_view(previous) if previous is not None else None,
        "subsequent": _run_link_view(subsequent) if subsequent is not None else None,
        "can_retry": retryable,
        "can_run": _holds(session, actor, f"agent.run.{run.agent_key}"),
        "is_awake": agent_state(session, run.agent_key)["mode"] == agent_models.AGENT_AWAKE,
    }


def _failed_work_detail(
    session: Session, actor: ActorContext, work: agent_ops.AgentWorkQueue
) -> dict[str, Any]:
    """Return a truthful detail view when work failed before a run was created."""
    application = session.get(permit.Application, work.application_id)
    return {
        "missing": False,
        "run_id": work.id,
        "agent_key": work.agent_key,
        "agent_label": AGENT_LABELS.get(work.agent_key, work.agent_key),
        "application_id": work.application_id,
        "reference": _number_of(session, work.application_id),
        "recorded_revision": "Not recorded",
        "current_revision": application.revision if application is not None else "Not available",
        "revision_matches": True,
        "triggered_by": "Not recorded",
        "service_identity": "Not recorded",
        "started_at": _iso(work.claimed_at) or "Not recorded",
        "finished_at": _iso(work.finished_at) or "Not recorded",
        "duration": "Not recorded",
        "state": "failed",
        "state_label": "Failed",
        "detail": work.note or "The work stopped before an agent run was created.",
        "engine_label": "Not started",
        "nodes": [],
        "model_runs": [],
        "findings": [],
        "previous": None,
        "subsequent": None,
        "can_retry": retry_allowed(work),
        "can_run": _holds(session, actor, f"agent.run.{work.agent_key}"),
        "is_awake": agent_state(session, work.agent_key)["mode"] == agent_models.AGENT_AWAKE,
    }


def _run_link_view(run: agent_models.AgentRun) -> dict[str, str]:
    """Return the concise label and route data for a neighboring attempt."""
    return {
        "run_id": run.id,
        "label": f"{RUN_STATE_LABELS.get(run.outcome, run.outcome)} at {_iso(run.started_at)}",
    }


def agent_case(session: Session, actor: ActorContext, application_id: str) -> dict[str, Any]:
    """Return the operational summary of one case.

    The summary is the work of the operator: the revision, the state of the
    processing, the findings and the recorded runs.  It asks for no grant
    beyond the operational one, so an operator never needs the broad grants
    of the permit workspace to read it.
    """
    application = session.get(permit.Application, application_id)
    if application is None:
        return {
            "missing": True,
            "application_id": application_id,
            "reference": "",
            "revision": 0,
            "status": "",
            "review_area": "",
            "permit_type_key": "",
            "state": "",
            "state_label": "",
            "attempts": 0,
            "note": "",
            "engine_label": BUILTIN_ENGINE_LABEL,
            "findings": [],
            "runs": [],
        }
    work = session.execute(
        select(agent_ops.AgentWorkQueue)
        .where(agent_ops.AgentWorkQueue.application_id == application_id)
        .order_by(agent_ops.AgentWorkQueue.created_at.desc())
    ).scalars().first()
    findings = list(
        session.execute(
            select(permit.ApplicationFinding)
            .where(
                permit.ApplicationFinding.application_id == application_id,
                permit.ApplicationFinding.state == "current",
            )
            .order_by(permit.ApplicationFinding.created_at.desc())
        ).scalars().all()
    )
    runs = list(
        session.execute(
            select(agent_models.AgentRun)
            .where(agent_models.AgentRun.application_id == application_id)
            .order_by(agent_models.AgentRun.started_at.desc(), agent_models.AgentRun.id.desc())
        ).scalars().all()
    )
    return {
        "application_id": application.id,
        "missing": False,
        "reference": application.source_application_number,
        "revision": application.revision,
        "status": application.status,
        "review_area": application.review_area or "",
        "permit_type_key": _type_key(session, application.permit_type_id),
        "state": work.status if work is not None else "",
        "state_label": _queue_state_label(work.status if work is not None else ""),
        "attempts": work.attempts if work is not None else 0,
        "note": work.note or "" if work is not None else "",
        "engine_label": BUILTIN_ENGINE_LABEL,
        "findings": [
            {
                "finding_id": row.id,
                "finding_type": row.finding_type,
                "message": row.message,
                "rule": row.rule or "",
                "severity": row.severity,
                "applicant_must": row.applicant_must or "",
                "recorded_at": _iso(row.created_at),
            }
            for row in findings
        ],
        "runs": [
            {
                "run_id": run.id,
                "agent_label": AGENT_LABELS.get(run.agent_key, run.agent_key),
                "state": run.outcome,
                "state_label": RUN_STATE_LABELS.get(run.outcome, run.outcome),
                "started_at": _iso(run.started_at),
                "duration": _duration(run),
                "engine_label": ENGINE_LABELS.get(_engine_of(run), _engine_of(run)),
                "triggered_label": _actor_label(session, run.triggered_by),
                "nodes": _run_nodes(session, run.id),
            }
            for run in runs
        ],
    }


def _queue_state_label(status: str) -> str:
    """Return what a state of the work queue means for the operator."""
    return {
        "pending": "Waiting",
        "running": "Running",
        "completed": "Completed",
        "failed": "Failed",
        "held": "Waiting for a person",
    }.get(status, status)


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
    "ENGINE_LABELS",
    "IN_REVIEW_STATUSES",
    "RUN_PAGE_SIZE",
    "RUN_STATE_LABELS",
    "SCREEN_ADMIN",
    "SCREEN_AGENT_ADJUDICATION",
    "SCREEN_AGENT_INTAKE",
    "STATUS_SUBMITTED",
    "administration",
    "agent_case",
    "agent_screen",
    "agent_state",
    "run_history",
    "sidebar_status",
]
