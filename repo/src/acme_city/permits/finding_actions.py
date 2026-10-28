"""The waiver a Data Steward records against a finding.

A waiver applies to a **current** finding of a **waivable** type.  It
records the reason code, the free-text reason, who waived it and when, and
the finding is then shown struck through with that detail.

A waiver never clears a deterministic rule failure and never clears an
identity, credential, finance or parcel-clearance check: those keep
blocking a decision exactly as they did before.  Only the intake findings
stop blocking the advance-to-review step.
"""
# REQUIRES: PER-04, SEC-03
# A waiver is an authorized, version-checked, audited action on a current
# finding of a waivable type, and it never clears a decision blocker.

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.agents.findings import WAIVABLE_TYPES
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.configuration.reasons import ReasonCodeSnapshot, reason_code_snapshot
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.permits.guard import require_mutable
from acme_city.persistence.models import permit

#: The grant that waives a finding.
PERMISSION_WAIVE = "permit.finding.waive"

#: The domain every permit action is authorized in.
PERMIT_DOMAIN = "permits"


def waive_finding(
    session: Session,
    *,
    finding_id: str,
    reason_code: str,
    reason: str,
    actor: ActorContext,
    expected_version: int | None,
    now: datetime | None = None,
) -> permit.ApplicationFinding:
    """Waive one current intake finding.

    The waiver is refused when the finding is not current, when its type
    may not be waived, when it was waived already, when the reason code is
    not an active waiver code, and when the case changed since it was
    read.
    """
    moment = now or utc_now()
    audit = AuditService(session, now=moment)
    permissions = PermissionResolver(session, now=moment)
    finding = session.execute(
        select(permit.ApplicationFinding).where(
            permit.ApplicationFinding.id == finding_id
        )
    ).scalar_one_or_none()
    if finding is None:
        raise NotFoundError("that finding does not exist")
    application = session.execute(
        select(permit.Application).where(
            permit.Application.id == finding.application_id
        )
    ).scalar_one_or_none()
    if application is None:
        raise NotFoundError("that application does not exist")
    permissions.authorize(
        actor,
        PERMISSION_WAIVE,
        ResourceContext(
            domain_id=PERMIT_DOMAIN,
            record_ids=(
                application.source_application_number,
                application.applicant_party_id or "",
            ),
        ),
    )
    if expected_version is None:
        raise ValidationError("an expected version is required to waive a finding")
    if application.version != expected_version:
        raise ValidationError(
            "the application changed since it was read; read it again and retry"
        )
    require_mutable(application, action="waiving the finding")
    if finding.state != "current":
        raise ValidationError(
            f"that finding is {finding.state}; only a current finding may be waived"
        )
    if finding.finding_type not in WAIVABLE_TYPES:
        raise ValidationError(f"a {finding.finding_type!r} finding may not be waived")
    if finding.waived_at is not None:
        raise ValidationError("that finding was already waived")
    text = str(reason or "").strip()
    if not text:
        raise ValidationError("a waiver needs a reason")
    snapshot = reason_code_snapshot(session, reason_code, code_type="waiver")
    finding.waived_at = moment
    finding.waived_by_actor_id = actor.actor_id
    finding.waiver_reason_code_id = snapshot.reason_code_id
    finding.waiver_reason_code = snapshot.code
    finding.waiver_reason_code_label = snapshot.label
    finding.waiver_reason_code_version = snapshot.version
    finding.waiver_reason = text
    finding.version += 1
    application.version += 1
    session.flush()
    _record_action(
        session,
        audit=audit,
        application=application,
        finding=finding,
        snapshot=snapshot,
        reason=text,
        actor=actor,
        moment=moment,
    )
    return finding


def _record_action(
    session: Session,
    *,
    audit: AuditService,
    application: permit.Application,
    finding: permit.ApplicationFinding,
    snapshot: ReasonCodeSnapshot,
    reason: str,
    actor: ActorContext,
    moment: datetime,
) -> permit.ApplicationAction:
    """Record the waiver as an action record and an audit event."""
    row = permit.ApplicationAction(
        id=new_id("appaction"),
        correlation_id=application.correlation_id or new_id("corr"),
        application_id=application.id,
        action="waive_finding",
        actor_id=actor.actor_id,
        occurred_at=moment,
        reason_code_id=snapshot.reason_code_id,
        reason_code=snapshot.code,
        reason_code_label=snapshot.label,
        reason_code_version=snapshot.version,
        reason=reason,
        metadata_json={
            "finding_id": finding.id,
            "finding_type": finding.finding_type,
        },
    )
    session.add(row)
    session.flush()
    audit.append(
        action="application.waive_finding",
        actor=actor,
        target_type="application",
        target_id=application.id,
        after_version=application.version,
        reason=reason,
        references=[row.id, finding.id],
        correlation_id=row.correlation_id,
        metadata={
            "action": "waive_finding",
            "reason_code": snapshot.code,
            "reason_code_label": snapshot.label,
            "reason_code_version": snapshot.version,
            "finding_id": finding.id,
            "finding_type": finding.finding_type,
        },
    )
    session.flush()


__all__ = [
    "PERMISSION_WAIVE",
    "waive_finding",
]
