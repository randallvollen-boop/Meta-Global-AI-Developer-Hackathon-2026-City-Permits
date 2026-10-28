"""The intake queue, the early-resolution board and the review queue.

Three queues answer three questions of the City:

* the **intake queue** shows the cases the Data Steward is responsible for,
  grouped into saved views with exact membership, searchable and filterable
  through the query string alone;
* the **early-resolution board** shows the cases that wait for a person, in
  the groups the primary finding of the case puts them in;
* the **review queue** shows the cases the Permit Reviewer has in front of
  them, by review area, with the recent decisions below.

Every count on these screens is a query over the stored rows.  Every figure
that is not a count — the age of a case, the service target of its type, the
signal of the agent — is either a stored fact or a stated definition, and
the screen says which.  A signal is shown only where the server holds the
fact behind it: there is no invented duplicate warning and no invented
confidence number.

Nothing here decides anything.  The queues name the actions a person may
take and the destination of each one; the server checks the grant, the
version and the state again when the action arrives.
"""
# REQUIRES: UX-01, UX-02, PER-03, PER-04, AI-03
# The three queues report the exact membership of each saved view, the age of
# every case against the configured service target of its type, and the
# signals the server actually holds; no figure is estimated and no outcome is
# decided on a queue.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.agents.findings import (
    FINDING_CATEGORY_ORDER,
    category_rank,
    current_findings,
    primary_finding,
)
from acme_city.auth.context import ActorContext
from acme_city.core.clock import app_now
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import governance, permit, registry

#: The saved views of the intake queue, in the order the tabs show them.
#:
#: Each view names the statuses it holds, exactly.  ``awaiting_agent`` is the
#: set of cases the intake agent is waiting for: a case that arrived from
#: outside the City, is still ``submitted`` and has no intake run for its
#: current revision.  A seeded demonstration case carries a scenario id and
#: is part of the fixed corpus, not an arrival, so it never waits.
INTAKE_TABS: tuple[dict[str, Any], ...] = (
    {
        "key": "active",
        "label": "Active",
        "statuses": (
            "submitted",
            "needs_information",
            "ready_for_review",
            "under_review",
            "revisions_requested",
        ),
        "description": "Every case that is still open.",
    },
    {
        "key": "awaiting_agent",
        "label": "Awaiting agent",
        "statuses": ("submitted",),
        "description": (
            "Cases that arrived from outside the City and have no intake run yet."
        ),
    },
    {
        "key": "needs_information",
        "label": "Needs information",
        "statuses": ("needs_information",),
        "description": "Cases that wait for the applicant or for a person.",
    },
    {
        "key": "in_review",
        "label": "In review",
        "statuses": ("ready_for_review", "under_review"),
        "description": "Cases that are with the Permit Reviewer.",
    },
    {
        "key": "archived",
        "label": "Archived",
        "statuses": ("archived",),
        "description": "Cases the City archived. A restore returns them.",
    },
    {
        "key": "closed",
        "label": "Closed",
        "statuses": ("issued", "denied", "returned"),
        "description": "Cases that are finished, returned or issued.",
    },
)

#: The keys of the intake tabs, in order.
INTAKE_TAB_KEYS: tuple[str, ...] = tuple(tab["key"] for tab in INTAKE_TABS)

#: The sorts the intake queue offers.
INTAKE_SORTS: tuple[tuple[str, str], ...] = (
    ("age", "Age, oldest first"),
    ("priority", "Priority, high first"),
    ("type", "Permit type, then age"),
    ("reference", "Reference"),
)

#: The signal a case carries when the server holds no fact for it.
SIGNAL_NONE = "none"


def _age_days(since: datetime | None, now: datetime) -> int | None:
    """Return the age of a record in whole days."""
    if since is None:
        return None
    return max((now - since).days, 0)


def _channel_of(application: permit.Application) -> str:
    """Return the channel the case arrived through."""
    facts = dict(application.submitted_facts or {})
    return str(facts.get("channel") or "unknown")


def _applicant_name(session: Session, application: permit.Application) -> str:
    """Return the name of the applicant of one case."""
    facts = dict(application.submitted_facts or {})
    stated = str(facts.get("applicant_name") or "").strip()
    if stated:
        return stated
    if application.applicant_party_id:
        party = session.get(registry.Party, application.applicant_party_id)
        if party is not None:
            return party.display_name
    return ""


def _address_of(session: Session, application: permit.Application) -> str:
    """Return the address the case was received for."""
    site = session.execute(
        select(permit.ApplicationSite).where(
            permit.ApplicationSite.application_id == application.id,
            permit.ApplicationSite.is_primary.is_(True),
        )
    ).scalars().first()
    if site is not None and site.submitted_address_text:
        return site.submitted_address_text
    facts = dict(application.submitted_facts or {})
    return str(facts.get("submitted_site_text") or facts.get("site_address") or "")


def is_arrival(application: permit.Application) -> bool:
    """Return whether the case arrived from outside the City.

    A seeded demonstration case carries a scenario id: it is part of the
    fixed corpus of the demonstration, not an arrival, so it never waits for
    the intake agent.  This is the same rule the intake agent screen uses
    for its ``Waiting`` figure.
    """
    return application.scenario_id is None


def _current_intake_run(
    session: Session, application: permit.Application
) -> agent_models.AgentRun | None:
    """Return the intake run of the current revision of one case.

    A run records the revision it ran against.  A run of an earlier revision
    is history: the case was answered again since, so the old run says
    nothing about the case as it stands.
    """
    rows = session.execute(
        select(agent_models.AgentRun)
        .where(
            agent_models.AgentRun.agent_key == agent_models.AGENT_INTAKE,
            agent_models.AgentRun.application_id == application.id,
        )
        .order_by(
            agent_models.AgentRun.started_at.desc(),
            agent_models.AgentRun.id.desc(),
        )
    ).scalars().all()
    for row in rows:
        recorded = (row.inputs or {}).get("revision")
        if recorded is not None and int(recorded) == int(application.revision):
            return row
    return None


def awaits_intake(
    session: Session, application: permit.Application
) -> bool:
    """Return whether the intake agent is waiting for this case."""
    return (
        application.status == "submitted"
        and is_arrival(application)
        and _current_intake_run(session, application) is None
    )


def _document_quality(session: Session, application_id: str) -> list[str]:
    """Return the scan-quality flags the received documents carry."""
    rows = session.execute(
        select(permit.Document).where(permit.Document.application_id == application_id)
    ).scalars().all()
    flags: list[str] = []
    for row in rows:
        for flag in row.quality or []:
            text = str(flag)
            if text and text not in flags:
                flags.append(text)
    return sorted(flags)


def _parcel_signal(
    session: Session, application: permit.Application
) -> dict[str, str]:
    """Return the parcel-match status the server holds for one case.

    The status comes from the recorded site and the recorded parcel link:
    ``no match``, ``proposed``, ``approved`` or ``confirmed``.  A case the
    locator never touched reports ``no match``; it is not an error.
    """
    from acme_city.gis.matching import ParcelMatchService

    site = session.execute(
        select(permit.ApplicationSite).where(
            permit.ApplicationSite.application_id == application.id,
            permit.ApplicationSite.is_primary.is_(True),
        )
    ).scalars().first()
    parcel_number = ""
    if site is not None and site.parcel_id:
        parcel = session.get(registry.Parcel, site.parcel_id)
        if parcel is not None:
            parcel_number = parcel.source_parcel_number
    match = ParcelMatchService(session).for_application(application.id)
    if match is None:
        status = "no match"
    elif match.confirmed_at is not None:
        status = "confirmed"
    elif match.link_state == "approved":
        status = "approved"
    else:
        status = "proposed"
    return {
        "status": status,
        "parcel_number": parcel_number,
        "detail": {
            "no match": "the locator did not match a parcel for this case",
            "proposed": "the locator proposed a parcel; the Data Steward approves it",
            "approved": "the Data Steward approved the parcel; the reviewer confirms it",
            "confirmed": "the Permit Reviewer confirmed the parcel",
        }[status],
    }


def _agent_signal(
    session: Session, application: permit.Application
) -> dict[str, str]:
    """Return the signal the intake agent left on one case.

    The agent leaves three signals, and they are the only ones the server
    holds: it asked for a person, it asked for information, or it was
    satisfied.  A case no agent has run on carries no signal at all.
    """
    run = _current_intake_run(session, application)
    if run is None:
        return {
            "state": "not run",
            "detail": "the intake agent has not run on this case yet",
        }
    if run.outcome == "needs_information":
        return {
            "state": "needs a person",
            "detail": "the intake agent routed this case to early resolution",
        }
    if run.outcome == "failed":
        return {
            "state": "failed",
            "detail": "the last intake run failed; a person must look",
        }
    return {
        "state": "agent was satisfied",
        "detail": "the intake agent found no blocking problem on this case",
    }


def _duplicate_signal(
    session: Session, application: permit.Application
) -> dict[str, str]:
    """Return the duplicate candidate the server holds for one case.

    The signal is the recorded duplicate finding of the intake run, with the
    reference of the other case when the finding names one.
    """
    for row in current_findings(session, application.id):
        if row.finding_type != "duplicate":
            continue
        other = ""
        if row.related_application_id:
            other_row = session.get(permit.Application, row.related_application_id)
            if other_row is not None:
                other = other_row.source_application_number
        return {
            "state": "possible duplicate",
            "detail": (
                f"the intake agent found a possible duplicate ({other})"
                if other
                else "the intake agent found a possible duplicate"
            ),
            "related_reference": other,
        }
    return {"state": SIGNAL_NONE, "detail": "", "related_reference": ""}


def _owner_labels(
    session: Session, applications: list[permit.Application]
) -> dict[str, str]:
    """Return the display label of every owner of the given cases."""
    owner_ids = {row.owner_actor_id for row in applications if row.owner_actor_id}
    if not owner_ids:
        return {}
    rows = session.execute(
        select(governance.Actor).where(governance.Actor.actor_id.in_(sorted(owner_ids)))
    ).scalars().all()
    return {row.actor_id: row.label for row in rows}


def _intake_row(
    session: Session,
    application: permit.Application,
    *,
    now: datetime,
    type_row: permit.PermitType,
    owner_label: str,
) -> dict[str, Any]:
    """Return one row of the intake queue."""
    age = _age_days(application.initial_submitted_at, now)
    target_days = int(type_row.service_target_days or 0)
    if age is None:
        age_tone = ""
    elif target_days and age > target_days:
        age_tone = "over"
    elif target_days and age == target_days:
        age_tone = "at"
    else:
        age_tone = ""
    duplicate = _duplicate_signal(session, application)
    parcel = _parcel_signal(session, application)
    agent = _agent_signal(session, application)
    quality = _document_quality(session, application.id)
    findings = current_findings(session, application.id)
    primary = primary_finding(findings)
    return {
        "application_id": application.id,
        "reference": application.source_application_number,
        "permit_type_id": type_row.id,
        "permit_type_key": type_row.key,
        "permit_type_label": type_row.label,
        "review_area": application.review_area or type_row.review_area or "",
        "status": application.status,
        "status_label": application.status.replace("_", " "),
        "channel": _channel_of(application),
        "priority": application.priority,
        "owner_actor_id": application.owner_actor_id or "",
        "owner_label": owner_label,
        "applicant_name": _applicant_name(session, application),
        "address": _address_of(session, application),
        "age_days": age,
        "service_target_days": target_days,
        "age_tone": age_tone,
        "version": application.version,
        "href": f"/permits/{application.id}",
        "awaiting_intake": awaits_intake(session, application),
        "signals": {
            "duplicate": duplicate,
            "document_quality": {
                "state": ", ".join(quality) if quality else SIGNAL_NONE,
                "detail": (
                    "the received pages carry a scan-quality flag" if quality else ""
                ),
                "flags": quality,
            },
            "parcel": parcel,
            "agent": agent,
        },
        "primary_finding": (
            {
                "finding_id": primary.id,
                "finding_type": primary.finding_type,
                "message": primary.message,
                "severity": primary.severity,
            }
            if primary is not None
            else None
        ),
        "blocking_findings": len(
            [
                row
                for row in findings
                if row.severity == "block" and row.waived_at is None
            ]
        ),
    }


def _type_rows(session: Session) -> dict[str, permit.PermitType]:
    """Return the permit types of the catalogue, keyed by identifier."""
    return {
        row.id: row
        for row in session.execute(select(permit.PermitType)).scalars().all()
    }


def _visible(session: Session, actor: ActorContext) -> list[permit.Application]:
    """Return the applications the acting persona may see."""
    from acme_city.ui.view_models import visible_applications

    return visible_applications(session, actor)


def intake_queue(
    session: Session,
    actor: ActorContext,
    *,
    tab: str = "active",
    query: str = "",
    channel: str = "",
    permit_type: str = "",
    priority: str = "",
    owner: str = "",
    sort: str = "age",
) -> dict[str, Any]:
    """Return the intake queue of the Data Steward.

    The queue shows the saved views with their exact membership, the filters
    that are in force and the rows that survive them.  Every filter is a
    query-string value, so the screen works without JavaScript.
    """
    now = app_now()
    tab_key = tab if tab in INTAKE_TAB_KEYS else "active"
    applications = _visible(session, actor)
    labels = _owner_labels(session, applications)
    type_rows = _type_rows(session)

    rows: list[dict[str, Any]] = []
    for application in applications:
        type_row = type_rows.get(application.permit_type_id)
        if type_row is None:
            continue
        rows.append(
            _intake_row(
                session,
                application,
                now=now,
                type_row=type_row,
                owner_label=labels.get(application.owner_actor_id or "", ""),
            )
        )

    def member(row: dict[str, Any], key: str) -> bool:
        """Return whether a row belongs to a saved view."""
        if key == "awaiting_agent":
            return bool(row["awaiting_intake"])
        return row["status"] in next(
            entry for entry in INTAKE_TABS if entry["key"] == key
        )["statuses"]

    counts = {
        entry["key"]: len([row for row in rows if member(row, entry["key"])])
        for entry in INTAKE_TABS
    }
    membership = [row for row in rows if member(row, tab_key)]

    filtered = membership
    if query.strip():
        needle = query.strip().lower()
        filtered = [
            row
            for row in filtered
            if needle in row["reference"].lower()
            or needle in row["applicant_name"].lower()
            or needle in row["address"].lower()
        ]
    if channel:
        filtered = [row for row in filtered if row["channel"] == channel]
    if permit_type:
        filtered = [row for row in filtered if row["permit_type_key"] == permit_type]
    if priority:
        filtered = [row for row in filtered if row["priority"] == priority]
    if owner:
        filtered = [row for row in filtered if (row["owner_actor_id"] or "") == owner]

    if sort == "priority":
        filtered.sort(
            key=lambda row: (
                0 if row["priority"] == "high" else 1,
                -(row["age_days"] or 0),
                row["reference"],
            )
        )
    elif sort == "type":
        filtered.sort(
            key=lambda row: (
                row["permit_type_label"],
                -(row["age_days"] or 0),
                row["reference"],
            )
        )
    elif sort == "reference":
        filtered.sort(key=lambda row: row["reference"])
    else:
        filtered.sort(key=lambda row: (-(row["age_days"] or 0), row["reference"]))

    return {
        "tab": tab_key,
        "tabs": [
            {
                "key": entry["key"],
                "label": entry["label"],
                "description": entry["description"],
                "count": counts[entry["key"]],
                "href": f"/queue/intake?tab={entry['key']}",
            }
            for entry in INTAKE_TABS
        ],
        "rows": filtered,
        "counts": counts,
        "total_in_tab": len(membership),
        "total_after_filters": len(filtered),
        "filters": {
            "tab": tab_key,
            "query": query.strip(),
            "channel": channel,
            "permit_type": permit_type,
            "priority": priority,
            "owner": owner,
            "sort": sort if sort in {key for key, _ in INTAKE_SORTS} else "age",
        },
        "sorts": [{"key": key, "label": label} for key, label in INTAKE_SORTS],
        "channels": sorted({row["channel"] for row in rows}),
        "permit_types": sorted(
            {
                (row["permit_type_key"], row["permit_type_label"])
                for row in rows
            }
        ),
        "priorities": ["high", "normal"],
        "owners": sorted(
            {
                (row["owner_actor_id"], row["owner_label"])
                for row in rows
                if row["owner_actor_id"]
            }
        ),
        "definitions": {
            "age": (
                "The age is the number of whole days since the first submission "
                "of the case."
            ),
            "target": (
                "The service target is the fictional number of days the City "
                "aims to review a case of that permit type in. It is a "
                "demonstration figure and makes no promise."
            ),
            "signals": (
                "A signal is shown only where the server holds the fact: the "
                "recorded duplicate finding, the scan-quality flags of the "
                "received documents, the recorded parcel link and what the "
                "intake agent left on the case."
            ),
        },
    }


def early_resolution(session: Session, actor: ActorContext) -> dict[str, Any]:
    """Return the early-resolution board of the Data Steward.

    The board groups the cases that wait for a person by the type of their
    primary finding, in the stable order the findings carry, and shows the
    top current findings of every group.  It is the same order the intake
    agent's findings are grouped by, so a case appears under one group only.
    """
    now = app_now()
    type_rows = _type_rows(session)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for application in _visible(session, actor):
        if application.status != "needs_information":
            continue
        type_row = type_rows.get(application.permit_type_id)
        if type_row is None:
            continue
        findings = current_findings(session, application.id)
        primary = primary_finding(findings)
        row = _intake_row(
            session,
            application,
            now=now,
            type_row=type_row,
            owner_label="",
        )
        by_type.setdefault(
            primary.finding_type if primary is not None else "no finding",
            [],
        ).append(
            {
                **row,
                "current_findings": [
                    {
                        "finding_id": finding.id,
                        "finding_type": finding.finding_type,
                        "message": finding.message,
                        "rule": finding.rule or "",
                        "applicant_must": finding.applicant_must or "",
                        "severity": finding.severity,
                        "waived": finding.waived_at is not None,
                    }
                    for finding in sorted(
                        findings,
                        key=lambda item: (
                            0 if item.severity == "block" else 1,
                            category_rank(item.finding_type),
                            item.id,
                        ),
                    )
                ],
            }
        )

    order = list(FINDING_CATEGORY_ORDER)
    groups: list[dict[str, Any]] = []
    for key in sorted(
        by_type,
        key=lambda name: (order.index(name) if name in order else len(order), name),
    ):
        members = by_type[key]
        members.sort(key=lambda row: (-(row["age_days"] or 0), row["reference"]))
        groups.append(
            {
                "finding_type": key,
                "label": key.replace("_", " "),
                "count": len(members),
                "cases": members,
                "top_findings": [
                    {
                        "finding_type": row["primary_finding"]["finding_type"],
                        "message": row["primary_finding"]["message"],
                        "severity": row["primary_finding"]["severity"],
                        "reference": row["reference"],
                        "href": row["href"],
                    }
                    for row in members
                    if row["primary_finding"] is not None
                ][:5],
            }
        )

    return {
        "groups": groups,
        "total_cases": sum(group["count"] for group in groups),
        "definitions": {
            "group": (
                "A case is grouped by its primary finding: the blocking "
                "finding first, otherwise the first in the stable order "
                + ", ".join(FINDING_CATEGORY_ORDER)
                + "."
            ),
            "resolve": (
                "Resolve means taking one of the record actions on the case: "
                "ask the applicant for information, return the case, advance "
                "it to review, or waive a finding."
            ),
        },
    }


def _outcome_label(decision: permit.Decision) -> str:
    """Return the outcome a person reads."""
    from acme_city.ui.view_models import decision_outcome_label

    return decision_outcome_label(decision)


def _in_scope(actor: ActorContext, application: permit.Application) -> bool:
    """Return whether a case is inside the record scope of the actor."""
    if not actor.record_scope:
        return True
    return (
        application.source_application_number in actor.record_scope
        or (application.applicant_party_id or "") in actor.record_scope
        or application.id in actor.record_scope
    )


def review_queue(
    session: Session, actor: ActorContext, *, area: str = ""
) -> dict[str, Any]:
    """Return the review queue of the Permit Reviewer.

    The queue lists the cases that are with the reviewer, grouped by the
    review area they were routed to, and the decisions that were recorded
    recently.  The adjudication recommendation of a case is shown when the
    agent has made one.
    """
    now = app_now()
    applications = _visible(session, actor)
    labels = _owner_labels(session, applications)
    type_rows = _type_rows(session)

    in_review: list[dict[str, Any]] = []
    for application in applications:
        if application.status not in ("ready_for_review", "under_review"):
            continue
        type_row = type_rows.get(application.permit_type_id)
        if type_row is None:
            continue
        row = _intake_row(
            session,
            application,
            now=now,
            type_row=type_row,
            owner_label=labels.get(application.owner_actor_id or "", ""),
        )
        recommendation = session.execute(
            select(permit.Recommendation)
            .where(permit.Recommendation.application_id == application.id)
            .order_by(permit.Recommendation.created_at.desc())
        ).scalars().first()
        row["recommendation"] = (
            {
                "recommendation_id": recommendation.id,
                "proposed_outcome": recommendation.proposed_outcome,
                "status": recommendation.status,
                "stale": recommendation.stale,
                "rationale": recommendation.rationale or "",
                "conditions": list(recommendation.conditions or []),
            }
            if recommendation is not None
            else None
        )
        in_review.append(row)

    area_counts: dict[str, int] = {}
    for row in in_review:
        name = row["review_area"] or "unassigned"
        area_counts[name] = area_counts.get(name, 0) + 1
    areas = sorted(area_counts)

    rows = in_review
    if area:
        rows = [row for row in rows if (row["review_area"] or "unassigned") == area]
    rows.sort(key=lambda row: (-(row["age_days"] or 0), row["reference"]))

    recent: list[dict[str, Any]] = []
    decisions = session.execute(
        select(permit.Decision).order_by(permit.Decision.decided_at.desc())
    ).scalars().all()
    for decision in decisions:
        if len(recent) >= 25:
            break
        application = session.get(permit.Application, decision.application_id)
        if application is None or not _in_scope(actor, application):
            continue
        type_row = type_rows.get(application.permit_type_id)
        recent.append(
            {
                "decision_id": decision.id,
                "reference": application.source_application_number,
                "permit_type_label": type_row.label if type_row is not None else "",
                "outcome": decision.outcome,
                "outcome_label": _outcome_label(decision),
                "conditions": list(decision.conditions or []),
                "decided_by_actor_id": decision.decided_by_actor_id,
                "decided_at": decision.decided_at.isoformat()
                if decision.decided_at
                else "",
                "reason": decision.reason or "",
                "href": f"/permits/{application.id}",
            }
        )

    return {
        "rows": rows,
        "areas": areas,
        "area_counts": area_counts,
        "area": area,
        "recent_decisions": recent,
        "total_in_review": sum(area_counts.values()),
        "definitions": {
            "in_review": (
                "A case is in review when it is ready for review or under "
                "review. The review area is the one the intake router sent "
                "it to."
            ),
            "recent": (
                "The recent decisions are the last decisions of record, "
                "newest first, with the outcome and the conditions that "
                "were recorded with them."
            ),
        },
    }


__all__ = [
    "INTAKE_SORTS",
    "INTAKE_TABS",
    "INTAKE_TAB_KEYS",
    "SIGNAL_NONE",
    "awaits_intake",
    "early_resolution",
    "intake_queue",
    "is_arrival",
    "review_queue",
]
