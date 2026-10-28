"""Confirming and reverting an agent recommendation.

The agent recommends; a person with the ``permit.decide`` grant decides.
Confirming a recommendation records the decision through the existing decision
service, with the confirming person as the decider of record.  Reverting a
recommendation needs a reason and returns the case to manual review.

A held recommendation cannot be confirmed: the card says that the reviewer
decides with the normal decision form.
"""
# REQUIRES: PER-04, SEC-03, REF-02
# Confirming records the decision of a person, never the decision of an agent,
# and reverting keeps the recommendation and its reason in the audit trail.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from acme_city.agents.adjudication import (
    OUTCOME_APPROVE,
    OUTCOME_CONDITIONS,
    OUTCOME_DENY,
    OUTCOME_HOLD,
    STATUS_CONFIRMED,
    STATUS_PENDING,
    STATUS_REVERTED,
)
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.permits.decisions import PermitDecisionCommand, PermitDecisionService
from acme_city.permits.guard import require_mutable
from acme_city.permits.service import PERMIT_DOMAIN, PermitService
from acme_city.persistence.models import permit

#: The recommendation outcomes a person may confirm, and the decision outcome
#: each one records.  A confirmed recommendation with conditions is still an
#: ``approved`` decision; the decision outcome vocabulary does not change.
CONFIRMABLE_OUTCOMES: dict[str, str] = {
    OUTCOME_APPROVE: "approved",
    OUTCOME_CONDITIONS: "approved",
    OUTCOME_DENY: "denied",
}


def load_recommendation(
    session: Session, recommendation_id: str, application_id: str
) -> permit.Recommendation:
    """Return the recommendation of one application."""
    row = session.get(permit.Recommendation, recommendation_id)
    if row is None or row.application_id != application_id:
        raise NotFoundError("that recommendation does not exist for this application")
    return row


def confirm(
    session: Session,
    *,
    recommendation_id: str,
    application_id: str,
    actor: ActorContext,
    reason: str = "",
    reason_code: str = "",
    expected_application_version: int | None = None,
    now: datetime | None = None,
) -> permit.Recommendation:
    """Confirm a recommendation and record the decision of the confirming person.

    The decision is recorded through the existing decision service, so the
    decider of record, the versions it was made against and the audit trail
    are the ones the rest of the application already uses.  A denial needs a
    denial reason code, exactly as a manual denial does.
    """
    moment = now or utc_now()
    PermissionResolver(session, now=moment).authorize(
        actor,
        "permit.decide",
        ResourceContext(domain_id=PERMIT_DOMAIN, record_ids=()),
    )
    recommendation = load_recommendation(session, recommendation_id, application_id)
    if recommendation.stale:
        raise ValidationError(
            "this recommendation is stale; the case has changed since it was made"
        )
    if recommendation.status != STATUS_PENDING:
        raise ValidationError(
            f"this recommendation is {recommendation.status}; only a pending "
            "recommendation can be confirmed"
        )
    outcome = recommendation.proposed_outcome
    if outcome == OUTCOME_HOLD:
        raise ValidationError(
            "this recommendation is held for a person; decide the case with the "
            "normal decision form"
        )
    decision_outcome = CONFIRMABLE_OUTCOMES.get(outcome)
    if decision_outcome is None:
        raise ValidationError(f"a {outcome!r} recommendation cannot be confirmed")

    conditions = [str(item) for item in (recommendation.conditions or [])]
    permits = PermitService(session, now=moment)
    application = permits.load_application(application_id)
    # An archived case is closed: its recommendation is not confirmed.
    require_mutable(application, action="confirming the recommendation")
    result = PermitDecisionService(session, now=moment).decide(
        PermitDecisionCommand(
            application_id=application_id,
            outcome=decision_outcome,
            reason=reason or f"Confirmed the agent recommendation ({outcome}).",
            reason_code=reason_code,
            expected_application_version=expected_application_version,
            conditions=conditions,
        ),
        actor,
    )
    decision_id = getattr(result, "value", None)
    decision_identifier = getattr(decision_id, "decision_id", "") or ""
    recommendation.status = STATUS_CONFIRMED
    recommendation.confirmed_by = actor.actor_id
    recommendation.confirmed_at = moment
    recommendation.decision_id = decision_identifier or None
    recommendation.version += 1
    session.flush()
    AuditService(session, now=moment).append(
        action="recommendation.confirm",
        actor=actor,
        target_type="application",
        target_id=application_id,
        after_version=recommendation.version,
        reason=(
            f"confirmed the agent recommendation ({outcome}); the decision of record "
            f"is {decision_outcome}"
        ),
        references=[recommendation.id, decision_identifier],
        metadata={
            "recommendation_id": recommendation.id,
            "proposed_outcome": outcome,
            "decision_outcome": decision_outcome,
            "conditions": conditions,
        },
    )
    return recommendation


def revert(
    session: Session,
    *,
    recommendation_id: str,
    application_id: str,
    reason: str,
    actor: ActorContext,
    now: datetime | None = None,
) -> permit.Recommendation:
    """Revert a recommendation and return the case to manual review."""
    moment = now or utc_now()
    PermissionResolver(session, now=moment).authorize(
        actor,
        "permit.decide",
        ResourceContext(domain_id=PERMIT_DOMAIN, record_ids=()),
    )
    if not reason.strip():
        raise ValidationError("reverting a recommendation requires a reason")
    recommendation = load_recommendation(session, recommendation_id, application_id)
    if recommendation.stale:
        raise ValidationError(
            "this recommendation is stale; the case has changed since it was made"
        )
    if recommendation.status != STATUS_PENDING:
        raise ValidationError(
            f"this recommendation is {recommendation.status}; only a pending "
            "recommendation can be reverted"
        )
    permits = PermitService(session, now=moment)
    application = permits.load_application(application_id)
    # An archived case is closed: its recommendation is not changed.
    require_mutable(application, action="reverting the recommendation")
    recommendation.status = STATUS_REVERTED
    recommendation.reverted_by = actor.actor_id
    recommendation.reverted_at = moment
    recommendation.revert_reason = reason.strip()
    recommendation.version += 1
    if application.status not in ("issued", "approved", "denied"):
        application.status = "under_review"
        application.version += 1
    session.flush()
    AuditService(session, now=moment).append(
        action="recommendation.revert",
        actor=actor,
        target_type="application",
        target_id=application_id,
        after_version=recommendation.version,
        reason=f"reverted the agent recommendation: {reason.strip()}",
        references=[recommendation.id],
        metadata={
            "recommendation_id": recommendation.id,
            "proposed_outcome": recommendation.proposed_outcome,
        },
    )
    return recommendation


def recommendation_view(row: permit.Recommendation) -> dict[str, Any]:
    """Return the view of one recommendation."""
    return {
        "recommendation_id": row.id,
        "application_id": row.application_id,
        "proposed_outcome": row.proposed_outcome,
        "status": row.status,
        "evidence_refs": list(row.evidence_refs or []),
        "conditions": list(row.conditions or []),
        "rationale": row.rationale or "",
        "muse_summary": row.muse_summary or "",
        "run_ref": row.run_ref or "",
        "confirmed_by": row.confirmed_by or "",
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else "",
        "reverted_by": row.reverted_by or "",
        "reverted_at": row.reverted_at.isoformat() if row.reverted_at else "",
        "revert_reason": row.revert_reason or "",
        "decision_id": row.decision_id or "",
        "version": row.version,
    }


__all__ = [
    "CONFIRMABLE_OUTCOMES",
    "confirm",
    "load_recommendation",
    "recommendation_view",
    "revert",
]
