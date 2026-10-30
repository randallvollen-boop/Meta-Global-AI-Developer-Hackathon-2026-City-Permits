"""The operations dashboard (S10) of the City Administrator.

Every figure is a query over stored rows and carries its definition.  Nothing
is estimated.  The seeded synthetic permit history is flagged ``synthetic`` on
its rows; by default it is left out of every figure, and the screen can show
it with a label (``synthetic=include``).
"""
# REQUIRES: UX-01, SEC-02
# Each dashboard figure is a count or a mean over stored rows, labelled with its
# definition; the synthetic history is excluded by default or labelled.

from __future__ import annotations

from collections import Counter
from datetime import datetime
from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.core.clock import app_now, utc_now
from acme_city.permits.queues import INTAKE_TABS
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import permit

#: The statuses of the P3b Active saved view: every case that is still open.
ACTIVE_STATUSES: tuple[str, ...] = next(
    tab["statuses"] for tab in INTAKE_TABS if tab["key"] == "active"
)

#: The statuses the review backlog counts: the cases with the Permit Reviewer.
REVIEW_BACKLOG_STATUSES: tuple[str, ...] = ("ready_for_review", "under_review")

#: The intake outcomes that count as a completed run.
COMPLETED_INTAKE_OUTCOMES: tuple[str, ...] = ("completed", "needs_information")

#: The two modes of the synthetic switch.
SYNTHETIC_MODES: tuple[str, ...] = ("exclude", "include")

#: The group of the figures that count the work that is open now.
WORKLOAD_GROUP = "workload"

#: The group of the figures that count the work the services recorded.
PROCESSING_GROUP = "processing"

#: The plain words of the statuses.
STATUS_LABELS: dict[str, str] = {
    "draft": "Draft",
    "submitted": "Submitted",
    "needs_information": "Needs information",
    "revisions_requested": "Revisions requested",
    "ready_for_review": "Ready for review",
    "under_review": "Under review",
    "approved": "Approved",
    "denied": "Denied",
    "withdrawn": "Withdrawn",
    "issued": "Issued",
    "returned": "Returned",
    "archived": "Archived",
}

#: The plain words of the decision outcomes.
OUTCOME_LABELS: dict[str, str] = {
    "approved": "Approved",
    "denied": "Denied",
    "modified": "Modified",
    "information_requested": "Information requested",
}


def _bar_svg(title: str, rows: list[dict[str, Any]], testid: str) -> str:
    """Return a horizontal bar chart as inline SVG.

    No library and no outside script: each bar carries a ``<title>`` and the
    page prints the same numbers in a table beside the chart.
    """
    if not rows:
        return ""
    peak = max(item["count"] for item in rows) or 1
    row_height = 26
    label_width = 170
    bar_room = 260
    height = row_height * len(rows) + 8
    parts: list[str] = []
    for position, item in enumerate(rows):
        y = 4 + position * row_height
        width = round(bar_room * item["count"] / peak)
        label = escape(str(item["label"]))
        parts.append(
            f"<g><title>{label}: {item['count']}</title>"
            f'<text x="{label_width - 8}" y="{y + 16}" text-anchor="end" class="chart-label">{label}</text>'
            f'<rect x="{label_width}" y="{y + 2}" width="{max(width, 1 if item["count"] else 0)}" '
            f'height="{row_height - 8}" rx="3" class="chart-bar"/>'
            f'<text x="{label_width + width + 6}" y="{y + 16}" class="chart-value">{item["count"]}</text></g>'
        )
    return (
        f'<svg class="ops-chart" role="img" viewBox="0 0 {label_width + bar_room + 50} {height}" '
        f'aria-label="{escape(title)}" data-testid="{testid}"><title>{escape(title)}</title>'
        f"{''.join(parts)}</svg>"
    )


def _chart(title: str, definition: str, rows: list[dict[str, Any]], testid: str) -> dict[str, Any]:
    return {
        "title": title,
        "definition": definition,
        "rows": rows,
        "total": sum(item["count"] for item in rows),
        "svg": _bar_svg(title, rows, testid),
        "testid": testid,
    }


def _channel_of(application: permit.Application) -> str:
    facts = dict(application.submitted_facts or {})
    return str(facts.get("channel") or "unknown")


def dashboard(
    session: Session, *, synthetic: str = "exclude", now: datetime | None = None
) -> dict[str, Any]:
    """Return the figures, the charts and their definitions.

    Args:
        session: The open session.
        synthetic: ``exclude`` (the default) leaves the synthetic history out of
            every figure; ``include`` counts it, and the screen says so.
        now: The moment the figures are read at.
    """
    mode = synthetic if synthetic in SYNTHETIC_MODES else "exclude"
    # The synthetic year is dated on the real calendar, so it is read on the
    # real clock; the demo scenario clock applies only when it is left out.
    moment = now or (utc_now() if mode == "include" else app_now())
    every_application = list(session.execute(select(permit.Application)).scalars().all())
    synthetic_ids = {row.id for row in every_application if row.synthetic}
    applications = [
        row for row in every_application if mode == "include" or row.id not in synthetic_ids
    ]
    included_ids = {row.id for row in applications}

    # -- active cases and their age
    active = [row for row in applications if row.status in ACTIVE_STATUSES]
    ages = [
        (moment - row.initial_submitted_at).total_seconds() / 86400
        for row in active
        if row.initial_submitted_at is not None
    ]
    average_age = round(sum(ages) / len(ages), 1) if ages else None

    # -- intake agent results
    runs = list(
        session.execute(
            select(agent_models.AgentRun)
            .where(agent_models.AgentRun.agent_key == agent_models.AGENT_INTAKE)
            .order_by(agent_models.AgentRun.started_at, agent_models.AgentRun.id)
        ).scalars().all()
    )
    runs = [run for run in runs if run.application_id in included_ids]
    first_run: dict[str, agent_models.AgentRun] = {}
    for run in runs:
        first_run.setdefault(run.application_id or "", run)
    with_a_run = len(first_run)
    early_incomplete = sum(1 for run in first_run.values() if run.outcome == "needs_information")
    processed = {
        run.application_id for run in runs if run.outcome in COMPLETED_INTAKE_OUTCOMES
    }

    # -- decisions
    decisions = [
        row
        for row in session.execute(select(permit.Decision)).scalars().all()
        if mode == "include" or not row.synthetic
    ]
    by_outcome = Counter(row.outcome for row in decisions)
    decision_rows = [
        {"label": OUTCOME_LABELS.get(key, key), "count": by_outcome[key]}
        for key in OUTCOME_LABELS
    ] + [
        {"label": key, "count": count}
        for key, count in sorted(by_outcome.items())
        if key not in OUTCOME_LABELS
    ]

    # -- needs a person
    needs_information = sum(1 for row in applications if row.status == "needs_information")
    held = sum(
        1
        for row in session.execute(
            select(permit.Recommendation).where(
                permit.Recommendation.status == "pending",
                permit.Recommendation.proposed_outcome == "hold",
            )
        ).scalars().all()
        if row.application_id in included_ids
    )

    def share(part: int, whole: int) -> str:
        return "no intake run yet" if not whole else f"{round(100 * part / whole)}%"

    figures = [
        {
            "key": "active",
            "label": "Active cases",
            "group": WORKLOAD_GROUP,
            "value": len(active),
            "display": str(len(active)),
            "definition": (
                "Applications in the Active saved view of the intake queue: "
                + ", ".join(STATUS_LABELS[s].lower() for s in ACTIVE_STATUSES)
                + "."
            ),
        },
        {
            "key": "average_age",
            "label": "Average age of active cases",
            "group": WORKLOAD_GROUP,
            "value": average_age,
            "display": "no active case" if average_age is None else f"{average_age} days",
            "definition": (
                "Mean of now minus the original submission time over the active cases, "
                "in days. A resubmission does not reset it. "
                f"As of {moment.isoformat()}."
            ),
        },
        {
            "key": "early_incomplete",
            "label": "Incomplete at first intake",
            "group": PROCESSING_GROUP,
            "value": early_incomplete,
            "display": share(early_incomplete, with_a_run)
            + (f" ({early_incomplete} of {with_a_run})" if with_a_run else ""),
            "definition": (
                "Distinct applications whose first intake run routed to needs information, "
                "divided by distinct applications with at least one intake run, all time."
            ),
        },
        {
            "key": "agent_processed",
            "label": "Applications processed by intake",
            "group": PROCESSING_GROUP,
            "value": len(processed),
            "display": str(len(processed)),
            "definition": (
                "Distinct applications with at least one completed intake run. A rerun "
                "adds a run row but not an application."
            ),
        },
        {
            "key": "decisions",
            "label": "Decisions recorded",
            "group": PROCESSING_GROUP,
            "value": len(decisions),
            "display": str(len(decisions)),
            "definition": "Decision rows, all time. The split by outcome is in the table below.",
        },
        {
            "key": "needs_a_person",
            "label": "Items needing attention",
            "group": WORKLOAD_GROUP,
            "value": needs_information + held,
            "display": str(needs_information + held),
            "definition": (
                f"Applications in needs information ({needs_information}) plus pending "
                f"adjudication recommendations held for a person ({held}). It is a count "
                "of items, not of distinct cases: one application and one held "
                "recommendation are two items."
            ),
            "components": [
                {
                    "label": "Applications in needs information",
                    "value": needs_information,
                },
                {
                    "label": "Recommendations held for a person",
                    "value": held,
                },
            ],
        },
    ]

    status_counts = Counter(row.status for row in applications)
    status_rows = [
        {"label": STATUS_LABELS.get(key, key), "count": status_counts[key]}
        for key in STATUS_LABELS
        if status_counts[key]
    ]
    channel_counts = Counter(_channel_of(row) for row in applications if row.status != "draft")
    channel_rows = [
        {"label": key, "count": count}
        for key, count in sorted(channel_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    area_counts = Counter(
        row.review_area or "not routed"
        for row in applications
        if row.status in REVIEW_BACKLOG_STATUSES
    )
    area_rows = [
        {"label": key, "count": count}
        for key, count in sorted(area_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    charts = [
        _chart(
            "Volume by status",
            "Applications by their current status.",
            status_rows,
            "chart-status",
        ),
        _chart(
            "Channel distribution",
            "Submitted applications (not drafts) by the channel they arrived through.",
            channel_rows,
            "chart-channel",
        ),
        _chart(
            "Backlog by review area",
            "Applications that are ready for review or under review, by the review area "
            "they were routed to.",
            area_rows,
            "chart-backlog",
        ),
    ]
    synthetic_count = len(synthetic_ids)
    return {
        "as_of": moment.isoformat(),
        "figures": figures,
        "decision_rows": decision_rows,
        "charts": charts,
        "applications_counted": len(applications),
        "synthetic": {
            "mode": mode,
            "available": synthetic_count > 0,
            "count": synthetic_count,
            "note": (
                f"{synthetic_count} synthetic applications are in the database. "
                + (
                    "They are counted in the figures below and labelled as synthetic."
                    if mode == "include"
                    else "They are left out of every figure below."
                )
                if synthetic_count
                else "No synthetic history is loaded; every figure is over real rows."
            ),
        },
    }


__all__ = [
    "ACTIVE_STATUSES",
    "COMPLETED_INTAKE_OUTCOMES",
    "PROCESSING_GROUP",
    "REVIEW_BACKLOG_STATUSES",
    "STATUS_LABELS",
    "WORKLOAD_GROUP",
    "dashboard",
]
