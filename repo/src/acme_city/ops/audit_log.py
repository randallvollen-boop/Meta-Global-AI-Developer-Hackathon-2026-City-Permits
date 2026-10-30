"""The audit log (S11) of the City Administrator.

A read-only screen over the append-only audit records.  It is not a second
trail: it reads ``audit_events`` and nothing else.  The type of the actor is
classified from the server's own identity data, never from a string the row
carries:

* **agent**: a service identity that holds an agent role (the intake agent and
  the adjudication agent);
* **person**: a persona the interface can select, or a staff user the
  Administration screen created for a persona role;
* **system**: every other identity, and an event with no actor.
"""
# REQUIRES: SEC-03, UX-01
# The audit log reads the existing append-only audit table, classifies the
# actor type from server-owned identity rows, and links a row to its record
# only for the target types that have a page.

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from acme_city.persistence.models import audit, governance, permit

#: The roles that make a service identity an agent.
AGENT_ROLE_IDS: frozenset[str] = frozenset({"intake_agent", "adjudication_agent"})

#: The actor types the filter offers.
ACTOR_TYPES: tuple[tuple[str, str], ...] = (
    ("person", "Person"),
    ("agent", "Agent"),
    ("system", "System"),
)

#: The number of rows on one page.
PAGE_SIZE = 40


def identity_sets(session: Session) -> tuple[set[str], set[str]]:
    """Return ``(person_ids, agent_ids)`` from the stored identity rows."""
    agent_ids = {
        row[0]
        for row in session.execute(
            select(governance.ActorRole.actor_id).where(
                governance.ActorRole.role_id.in_(AGENT_ROLE_IDS)
            )
        ).all()
    }
    people = {
        row[0]
        for row in session.execute(
            select(governance.Actor.actor_id).where(
                or_(
                    governance.Actor.selectable.is_(True),
                    governance.Actor.persona_role.is_not(None),
                )
            )
        ).all()
    }
    return people - agent_ids, agent_ids


def actor_type_of(actor_id: str | None, person_ids: set[str], agent_ids: set[str]) -> str:
    """Return ``person``, ``agent`` or ``system`` for one actor identifier."""
    if actor_id and actor_id in agent_ids:
        return "agent"
    if actor_id and actor_id in person_ids:
        return "person"
    return "system"


def _record_links(session: Session, events: list[audit.AuditEvent]) -> dict[str, str]:
    """Return the page of each event's record, for the target types that have one."""
    wanted: dict[str, set[str]] = {"decision": set(), "permit": set(), "evaluation": set()}
    for event in events:
        if event.target_type in wanted and event.target_id:
            wanted[event.target_type].add(event.target_id)
    owner: dict[tuple[str, str], str] = {}
    if wanted["decision"]:
        for row in session.execute(
            select(permit.Decision.id, permit.Decision.application_id).where(
                permit.Decision.id.in_(wanted["decision"])
            )
        ).all():
            owner[("decision", row[0])] = row[1]
    if wanted["permit"]:
        for row in session.execute(
            select(permit.Permit.id, permit.Permit.application_id).where(
                permit.Permit.id.in_(wanted["permit"])
            )
        ).all():
            owner[("permit", row[0])] = row[1]
    if wanted["evaluation"]:
        for row in session.execute(
            select(permit.Evaluation.id, permit.Evaluation.application_id).where(
                permit.Evaluation.id.in_(wanted["evaluation"])
            )
        ).all():
            owner[("evaluation", row[0])] = row[1]
    links: dict[str, str] = {}
    for event in events:
        target, target_id = event.target_type or "", event.target_id or ""
        href = ""
        if target == "application" and target_id:
            href = f"/permits/{target_id}"
        elif (target, target_id) in owner:
            href = f"/permits/{owner[(target, target_id)]}"
        elif target == "policy_scenario" and target_id:
            href = f"/policy/scenarios/{target_id}"
        elif target == "policy_run" and target_id:
            href = f"/policy/runs/{target_id}"
        elif target == "help_request" and target_id:
            href = f"/ops/support?request={target_id}"
        elif target == "checks_run" and target_id:
            href = f"/ops/checks?run={target_id}"
        if href:
            links[event.id] = href
    return links


def application_references(session: Session, application_ids: set[str]) -> dict[str, str]:
    """Return the reference number of every named application."""
    if not application_ids:
        return {}
    return {
        row[0]: row[1]
        for row in session.execute(
            select(permit.Application.id, permit.Application.source_application_number).where(
                permit.Application.id.in_(application_ids)
            )
        ).all()
    }


def target_reference(session: Session, target_type: str, target_id: str) -> str:
    """Return the reference number of the record an event is about.

    A case is shown by the reference number the City uses everywhere else
    (``SYN-APP-001``); the internal identifier stays in the link that opens
    the case.
    """
    if target_type != "application" or not target_id:
        return ""
    return application_references(session, {target_id}).get(target_id, "")


def audit_log(
    session: Session,
    *,
    actor_type: str = "",
    action: str = "",
    search: str = "",
    page: int = 1,
) -> dict[str, Any]:
    """Return one page of the audit log, newest first."""
    person_ids, agent_ids = identity_sets(session)
    statement = select(audit.AuditEvent)
    kind = actor_type if actor_type in dict(ACTOR_TYPES) else ""
    if kind == "person":
        statement = statement.where(audit.AuditEvent.actor_id.in_(person_ids or {""}))
    elif kind == "agent":
        statement = statement.where(audit.AuditEvent.actor_id.in_(agent_ids or {""}))
    elif kind == "system":
        known = person_ids | agent_ids
        statement = statement.where(
            or_(
                audit.AuditEvent.actor_id.is_(None),
                audit.AuditEvent.actor_id.not_in(known or {""}),
            )
        )
    wanted_action = action.strip()
    if wanted_action:
        statement = statement.where(audit.AuditEvent.action == wanted_action)
    needle = search.strip()
    if needle:
        like = f"%{needle.lower()}%"
        statement = statement.where(
            or_(
                func.lower(audit.AuditEvent.action).like(like),
                func.lower(func.coalesce(audit.AuditEvent.target_type, "")).like(like),
                func.lower(func.coalesce(audit.AuditEvent.target_id, "")).like(like),
                func.lower(func.coalesce(audit.AuditEvent.actor_id, "")).like(like),
            )
        )
    total = int(
        session.execute(select(func.count()).select_from(statement.subquery())).scalar_one() or 0
    )
    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    current = min(max(int(page or 1), 1), pages)
    events = list(
        session.execute(
            statement.order_by(audit.AuditEvent.occurred_at.desc(), audit.AuditEvent.id.desc())
            .limit(PAGE_SIZE)
            .offset((current - 1) * PAGE_SIZE)
        ).scalars().all()
    )
    labels = {
        row[0]: row[1]
        for row in session.execute(
            select(governance.Actor.actor_id, governance.Actor.label).where(
                governance.Actor.actor_id.in_({e.actor_id for e in events if e.actor_id} or {""})
            )
        ).all()
    }
    links = _record_links(session, events)
    references = application_references(
        session,
        {
            event.target_id
            for event in events
            if event.target_type == "application" and event.target_id
        },
    )
    rows = [
        {
            "event_id": event.id,
            "occurred_at": event.occurred_at.isoformat() if event.occurred_at else "",
            "actor_id": event.actor_id or "",
            "actor_label": labels.get(event.actor_id or "", ""),
            "actor_type": actor_type_of(event.actor_id, person_ids, agent_ids),
            "action": event.action,
            "target_type": event.target_type or "",
            "target_id": event.target_id or "",
            "target_reference": references.get(event.target_id or "", ""),
            "href": links.get(event.id, ""),
            "outcome": event.outcome,
            "versions": (
                f"{event.before_version if event.before_version is not None else '-'}"
                f" to {event.after_version if event.after_version is not None else '-'}"
            ),
            "reason": event.reason or event.denial_reason or "",
            "basis": str((event.metadata_json or {}).get("approval_basis_label", "")),
        }
        for event in events
    ]
    actions = [
        row[0]
        for row in session.execute(
            select(audit.AuditEvent.action).distinct().order_by(audit.AuditEvent.action)
        ).all()
    ]
    return {
        "rows": rows,
        "total": total,
        "page": current,
        "pages": pages,
        "page_size": PAGE_SIZE,
        "filters": {"actor_type": kind, "action": wanted_action, "search": needle},
        "query": urlencode(
            {
                name: value
                for name, value in (
                    ("actor_type", kind),
                    ("action", wanted_action),
                    ("search", needle),
                )
                if value
            }
        ),
        "actor_types": [{"key": k, "label": v} for k, v in ACTOR_TYPES],
        "actions": actions,
    }


def event_detail(session: Session, event_id: str) -> audit.AuditEvent | None:
    """Return one audit event, or ``None``."""
    return session.get(audit.AuditEvent, event_id)


__all__ = [
    "ACTOR_TYPES",
    "AGENT_ROLE_IDS",
    "PAGE_SIZE",
    "actor_type_of",
    "application_references",
    "audit_log",
    "event_detail",
    "identity_sets",
    "target_reference",
]
