"""Typed reason codes.

A reason code names why a case was returned, denied, waived, sent back for
revisions or archived.  Its ``code_type`` says which of those uses it may
serve, so a denial code can never return a case and a waiver code can never
archive one.

The code is validated in the service that acts on a case, not only in the
form that offers it: an unknown code, a retired code and a wrongly typed
code are all refused.  The action record keeps the code, its label and its
version as they were at that moment, so the history of a case stays readable
after a code is retired.
"""
# REQUIRES: GOV-04, PER-04
# A reason code carries the type of use it may serve, an active code of the
# right type is validated in the underlying service, and the action record
# snapshots the code, its label and its version.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.core.errors import ValidationError
from acme_city.persistence.models import permit

#: The uses a reason code may serve.
REASON_CODE_TYPES: tuple[str, ...] = (
    "return",
    "denial",
    "waiver",
    "revision",
    "archive",
)


@dataclass(frozen=True)
class ReasonCodeSnapshot:
    """The reason code as it was at the moment an action was recorded.

    The snapshot keeps the code, its label and its version so that a retired
    code still reads correctly in the history of a case.
    """

    reason_code_id: str
    code: str
    label: str
    version: int

    def as_dict(self) -> dict[str, Any]:
        """Return the serialisable form of the snapshot."""
        return {
            "reason_code_id": self.reason_code_id,
            "code": self.code,
            "label": self.label,
            "version": self.version,
        }


def reason_code_snapshot(
    session: Session, code: str, *, code_type: str
) -> ReasonCodeSnapshot:
    """Return the snapshot of one active reason code of the right type.

    A code that does not exist, that has been retired, or that serves
    another use is refused here, so the refusal happens in the service that
    acts on the case and not only in the form.
    """
    if code_type not in REASON_CODE_TYPES:
        raise ValidationError(
            f"unknown reason code type: {code_type!r}; use one of "
            + ", ".join(REASON_CODE_TYPES)
        )
    clean = str(code or "").strip().upper()
    if not clean:
        raise ValidationError("a reason code is required for this action")
    row = session.execute(
        select(permit.ReasonCode).where(permit.ReasonCode.code == clean)
    ).scalar_one_or_none()
    if row is None:
        raise ValidationError(f"the reason code {clean!r} is not configured")
    if not row.active:
        raise ValidationError(f"the reason code {clean!r} has been retired")
    if row.code_type != code_type:
        raise ValidationError(
            f"the reason code {clean!r} serves {row.code_type!r}, not {code_type!r}"
        )
    return ReasonCodeSnapshot(
        reason_code_id=row.id,
        code=row.code,
        label=row.label,
        version=row.version,
    )


def active_reason_codes(
    session: Session, *, code_type: str | None = None
) -> list[ReasonCodeSnapshot]:
    """Return the active reason codes, optionally of one type only."""
    statement = select(permit.ReasonCode).where(permit.ReasonCode.active.is_(True))
    if code_type is not None:
        statement = statement.where(permit.ReasonCode.code_type == code_type)
    rows = session.execute(statement.order_by(permit.ReasonCode.code)).scalars().all()
    return [
        ReasonCodeSnapshot(
            reason_code_id=row.id,
            code=row.code,
            label=row.label,
            version=row.version,
        )
        for row in rows
    ]


def reason_code_view(row: permit.ReasonCode) -> dict[str, Any]:
    """Return the readable form of one stored reason code."""
    return {
        "reason_code_id": row.id,
        "code": row.code,
        "label": row.label,
        "description": row.description or "",
        "code_type": row.code_type,
        "active": bool(row.active),
        "version": row.version,
    }


__all__ = [
    "REASON_CODE_TYPES",
    "ReasonCodeSnapshot",
    "active_reason_codes",
    "reason_code_snapshot",
    "reason_code_view",
]
