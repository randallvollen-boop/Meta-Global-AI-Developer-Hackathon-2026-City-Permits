"""Applicant notices, derived from what the case already records.

The City tells an applicant about each decision and about the issued permit.
The demonstration sends no email, so a notice is not stored on its own: it is
read back from the recorded decisions and the issued permit of the case.  This
keeps the notice and the record from ever disagreeing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.persistence.models import permit

#: Said once beside every list of notices.
NOTICE_DISCLAIMER = "The demonstration sends no email."

#: Said at the end of the success message of a decision or an issuance.
ACTION_NOTE = "Email notice recorded for the applicant (the demonstration sends no email)."

#: Said once on the applicant's tracker.
TRACKER_NOTE = "The City would also send this by email. The demonstration sends no email."


def _stamp(value: datetime | None) -> str:
    if value is None:
        return ""
    return f"{value:%b} {value.day}, {value.year}, {value:%H:%M} UTC"


def _body(reason: str | None, conditions: list[Any], lead: str) -> str:
    parts = [lead]
    if reason and reason.strip():
        parts.append(f"The reviewer wrote: {reason.strip()}")
    cleaned = [str(item).strip() for item in conditions or [] if str(item).strip()]
    if cleaned:
        parts.append("Conditions: " + "; ".join(cleaned) + ".")
    return " ".join(parts)


def _decision_notice(row: permit.Decision, noun: str) -> tuple[str, str]:
    conditions = list(row.conditions or [])
    if row.outcome == "approved" and conditions:
        return (
            f"Your {noun} is approved with conditions",
            _body(row.reason, conditions, "The City approved your application, with conditions."),
        )
    if row.outcome == "approved":
        return (
            f"Your {noun} is approved",
            _body(row.reason, [], "The City approved your application."),
        )
    if row.outcome == "denied":
        return (
            f"Your {noun} was denied",
            _body(row.reason, [], "The City denied your application."),
        )
    if row.outcome == "information_requested":
        return (
            f"The City needs more information for your {noun}",
            _body(row.reason, [], "The City needs more from you before it can decide."),
        )
    return (
        f"The City changed what it will approve for your {noun}",
        _body(row.reason, conditions, "The City will not approve the application as submitted."),
    )


def applicant_notices(session: Session, application: permit.Application) -> list[dict[str, str]]:
    """Return the notices the applicant of one case is owed, newest first."""
    permit_type = session.get(permit.PermitType, application.permit_type_id)
    noun = (permit_type.label.lower() if permit_type else "permit") + " permit"
    notices: list[tuple[datetime, dict[str, str]]] = []
    decisions = session.execute(
        select(permit.Decision).where(permit.Decision.application_id == application.id)
    ).scalars().all()
    for row in decisions:
        subject, body = _decision_notice(row, noun)
        notices.append(
            (row.decided_at, {"kind": "decision", "when": _stamp(row.decided_at),
                              "subject": subject, "body": body})
        )
    issued = session.execute(
        select(permit.Permit).where(permit.Permit.application_id == application.id)
    ).scalars().all()
    for row in issued:
        notices.append(
            (
                row.issued_at,
                {
                    "kind": "issued",
                    "when": _stamp(row.issued_at),
                    "subject": f"Your permit {row.permit_number} is issued",
                    "body": f"The City issued permit {row.permit_number} for your application.",
                },
            )
        )
    notices.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in notices]


__all__ = ["ACTION_NOTE", "NOTICE_DISCLAIMER", "TRACKER_NOTE", "applicant_notices"]
