"""Accept or correct one proposed extracted value.

Extraction observations are proposals.  A steward accepts one (it becomes
part of the recorded proposed values) or corrects it with a replacement
value and a reason.  Accepting a value never rewrites the submitted
revision: the correction path for submitted facts remains a new revision.
"""
# REQUIRES: AI-03, PER-03
# A proposed value is accepted or corrected by a steward with a reason; the
# submitted revision is never rewritten by an acceptance.

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.persistence.models import permit


def decide_extraction(
    session: Session,
    *,
    observation_id: str,
    decision: str,
    corrected_value: str | None,
    reason: str,
    actor: ActorContext,
    now: datetime | None = None,
) -> permit.ExtractionObservation:
    """Record the steward decision on one extraction observation."""
    row = session.get(permit.ExtractionObservation, observation_id)
    if row is None:
        raise NotFoundError("that extraction observation does not exist")
    document = session.get(permit.Document, row.document_id)
    application_id = document.application_id if document else None
    PermissionResolver(session, now=now).authorize(
        actor,
        "application.revision.submit",
        ResourceContext(domain_id="permits", record_ids=(application_id or "",)),
    )
    if decision not in {"accept", "correct"}:
        raise ValidationError("an extraction decision is 'accept' or 'correct'")
    if decision == "correct":
        if not corrected_value or not corrected_value.strip():
            raise ValidationError("correcting a proposed value requires the corrected value")
        if not reason.strip():
            raise ValidationError("correcting a proposed value requires a reason")
        row.proposed_value = corrected_value.strip()
        row.validation_state = "corrected"
    else:
        row.validation_state = "accepted"
    session.flush()
    AuditService(session, now=now).append(
        action="extraction.decide",
        actor=actor,
        target_type="application",
        target_id=application_id or row.document_id,
        reason=f"steward {decision} of extracted {row.field_path}"
        + (f": {reason.strip()}" if reason.strip() else ""),
        references=[row.id],
        metadata={"decision": decision, "field_path": row.field_path},
    )
    return row


__all__ = ["decide_extraction"]
