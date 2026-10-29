"""The view model of the administration screen.

The screen reports the permit-type configuration, the people and the service
identities, the reason codes and the configuration log.  Nothing here decides
anything: every change is a governed action that the server checks.  The
functions were moved here from ``agent_views``, which still re-exports
``administration``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.persistence.models import audit, governance, permit


def _iso(value) -> str:
    """Return a display-safe timestamp."""
    return value.isoformat() if value is not None else ""


def _actor_label(session: Session, actor_id: str | None) -> str:
    """Return the display label of one actor."""
    from acme_city.ui.view_models import actor_label

    return actor_label(session, actor_id)


def _holds(session: Session, actor: ActorContext, permission: str) -> bool:
    """Return whether the actor holds one grant."""
    from acme_city.auth.permissions import PermissionResolver

    return any(
        grant.action == permission
        for grant in PermissionResolver(session).grants_for(actor.actor_id)
    )


def _permit_type_rows(session: Session) -> list[permit.PermitType]:
    """Return every permit type, in catalogue order."""
    return list(
        session.execute(
            select(permit.PermitType).order_by(permit.PermitType.label)
        ).scalars().all()
    )


#: The label of a permit type that is always held for a person or a board.
REQUIRES_A_PERSON = "Requires a person or board"

#: The label of a permit type that is not always held for a person or a board.
NO_PERSON_REQUIRED = "Does not require a person or board"

#: The label of a value that was never recorded.
NOT_RECORDED = "Not recorded"


def _names(values: list[str] | None) -> str:
    """Return the names of a list of stored values, in plain words."""
    names = [str(value).replace("_", " ") for value in values or []]
    return ", ".join(names) if names else NOT_RECORDED


def _requirements_summary(row: permit.PermitType) -> str:
    """Return the short summary of what a permit type asks for."""
    documents = [str(value).replace("_", " ") for value in row.required_documents or []]
    if not documents:
        return "No required document"
    if len(documents) == 1:
        return documents[0]
    return ", ".join(documents[:-1]) + " and " + documents[-1]


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
            "review_area_label": (row.review_area or row.review_route) or NOT_RECORDED,
            "process_category": row.process_category or "",
            "process_label": (row.process_category or "").replace("_", " ") or NOT_RECORDED,
            "discretionary": bool(row.discretionary),
            "discretionary_label": (
                REQUIRES_A_PERSON if row.discretionary else NO_PERSON_REQUIRED
            ),
            "required_fields": list(row.required_fields or []),
            "required_fields_label": _names(row.required_fields),
            "required_documents": list(row.required_documents or []),
            "required_documents_label": _names(row.required_documents),
            "requirements_summary": _requirements_summary(row),
            "fee_schedule_key": row.fee_schedule_key or "",
            "fee_schedule_label": row.fee_schedule_key or NOT_RECORDED,
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
        "persona_agent_operator": "Agent Operator",
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
            "code_type": row.code_type,
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
    "NO_PERSON_REQUIRED",
    "NOT_RECORDED",
    "REQUIRES_A_PERSON",
    "administration",
]
