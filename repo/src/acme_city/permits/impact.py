"""Impact of a source or catalogue change on the permit history.

A change that a decision depended on invalidates the pending work it affects
and nothing else.  A pending case is revalidated, an approved but unissued
case needs a reviewer reconfirmation, and an issued case keeps its snapshot
and receives a separate impact review.  No issued record is ever amended,
revoked or reissued silently.
"""
# REQUIRES: CHG-03, CHG-04, PER-03, PER-05
# A dependency change invalidates only the affected pending work and creates
# one assigned review record per affected case.  Issued history is preserved.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import ValidationError
from acme_city.core.ids import new_id
from acme_city.permits.schemas import PermitModel
from acme_city.permits.service import PERMIT_DOMAIN, PermitService
from acme_city.persistence.models import permit

#: The reviewer who receives the assigned impact work by default.
DEFAULT_REVIEWER_ACTOR_ID = "persona_permit_reviewer"


class ChangeImpactCommand(PermitModel):
    """Describe a change that the permit history depends on."""

    kind: str
    identifier: str
    reason: str = ""
    detail: str | None = None
    assigned_actor_id: str | None = None


class AffectedCase(PermitModel):
    """One case that a change affects."""

    application_id: str
    source_application_number: str
    state: str
    action: str
    evaluation_id: str | None = None
    decision_id: str | None = None
    permit_id: str | None = None
    impact_review_id: str | None = None


class ImpactSummary(PermitModel):
    """What a change affected."""

    kind: str
    identifier: str
    dependency_key: str
    affected: list[AffectedCase] = []
    unchanged_applications: list[str] = []


class ImpactService:
    """Applies the impact of a change to the permit history."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)
        self._permits = PermitService(session, now=self._now)

    def apply_change(
        self, command: ChangeImpactCommand, actor: ActorContext
    ) -> ImpactSummary:
        """Mark the affected cases and open one review record for each."""
        kind = str(command.kind or "").strip()
        identifier = str(command.identifier or "").strip()
        if not kind or not identifier:
            raise ValidationError("a change impact names a kind and an identifier")
        self._permissions.authorize(
            actor,
            "change.case.transition",
            ResourceContext(domain_id=PERMIT_DOMAIN, record_type="dependency"),
        )
        dependency_key = f"{kind}:{identifier}"

        evaluations = self._session.execute(
            select(permit.Evaluation).order_by(permit.Evaluation.application_id)
        ).scalars().all()
        affected_ids = {
            evaluation.application_id
            for evaluation in evaluations
            if dependency_key
            in (dict(evaluation.source_versions or {}).get("dependencies") or [])
        }
        permits = self._session.execute(
            select(permit.Permit).order_by(permit.Permit.application_id)
        ).scalars().all()
        for issued in permits:
            if dependency_key in _permit_dependencies(issued.snapshot or {}):
                affected_ids.add(issued.application_id)
        untouched = [
            application.source_application_number
            for application in self._session.execute(
                select(permit.Application).order_by(permit.Application.source_application_number)
            )
            .scalars()
            .all()
            if application.id not in affected_ids
        ]

        cases: list[AffectedCase] = []
        for application_id in sorted(affected_ids):
            cases.append(self._apply_to_case(application_id, dependency_key, command, actor))
        self._session.flush()

        self._audit.append(
            action="permit.impact.apply",
            actor=actor,
            target_type="dependency",
            target_id=dependency_key,
            reason=command.reason or None,
            references=[case.application_id for case in cases],
            metadata={"affected": len(cases)},
        )
        self._session.flush()
        return ImpactSummary(
            kind=kind,
            identifier=identifier,
            dependency_key=dependency_key,
            affected=cases,
            unchanged_applications=untouched,
        )

    def _apply_to_case(
        self,
        application_id: str,
        dependency_key: str,
        command: ChangeImpactCommand,
        actor: ActorContext,
    ) -> AffectedCase:
        """Apply the impact of a change to one application."""
        application = self._permits.load_application(application_id)
        evaluation = self._permits.current_evaluation(application_id)
        decision = self._permits.current_decision(application_id)
        issued = self._session.execute(
            select(permit.Permit).where(permit.Permit.application_id == application_id)
        ).scalar_one_or_none()

        reason = (
            f"{command.reason} (the {dependency_key} record changed)"
            if command.reason
            else f"the {dependency_key} record changed"
        )
        assigned = command.assigned_actor_id or DEFAULT_REVIEWER_ACTOR_ID

        if issued is not None:
            # The issued snapshot stays exactly as it is.
            review = self._open_review(
                target_type="permit",
                target_id=issued.id,
                reason=(
                    f"{reason}. The issued permit {issued.permit_number} keeps its snapshot; "
                    "an amendment route is required."
                ),
                assigned_actor_id=assigned,
                dependency_key=dependency_key,
            )
            return AffectedCase(
                application_id=application.id,
                source_application_number=application.source_application_number,
                state="issued",
                action="impact_review",
                evaluation_id=None if evaluation is None else evaluation.id,
                decision_id=None if decision is None else decision.id,
                permit_id=issued.id,
                impact_review_id=review.id,
            )

        if decision is not None:
            decision.stale = True
            decision.version += 1
            if evaluation is not None:
                evaluation.stale = True
            review = self._open_review(
                target_type="decision",
                target_id=decision.id,
                reason=(
                    f"{reason}. The approval is stale and needs a reviewer reconfirmation "
                    "against the current versions."
                ),
                assigned_actor_id=assigned,
                dependency_key=dependency_key,
            )
            return AffectedCase(
                application_id=application.id,
                source_application_number=application.source_application_number,
                state="approved_unissued",
                action="reconfirm",
                evaluation_id=None if evaluation is None else evaluation.id,
                decision_id=decision.id,
                impact_review_id=review.id,
            )

        if evaluation is not None:
            evaluation.stale = True
            review = self._open_review(
                target_type="evaluation",
                target_id=evaluation.id,
                reason=f"{reason}. The evaluation must be run again against the current versions.",
                assigned_actor_id=assigned,
                dependency_key=dependency_key,
            )
            return AffectedCase(
                application_id=application.id,
                source_application_number=application.source_application_number,
                state="pending",
                action="revalidate",
                evaluation_id=evaluation.id,
                impact_review_id=review.id,
            )

        return AffectedCase(
            application_id=application.id,
            source_application_number=application.source_application_number,
            state="not_evaluated",
            action="none",
        )

    def _open_review(
        self,
        *,
        target_type: str,
        target_id: str,
        reason: str,
        assigned_actor_id: str,
        dependency_key: str = "",
    ) -> permit.ImpactReview:
        """Open one assigned impact review for a target.

        The same dependency and target never produce two open reviews.
        """
        existing = self._session.execute(
            select(permit.ImpactReview).where(
                permit.ImpactReview.target_type == target_type,
                permit.ImpactReview.target_id == target_id,
                permit.ImpactReview.status == "open",
            )
        ).scalars().all()
        for review in existing:
            if _same_dependency(review.reason, dependency_key):
                return review
        review = permit.ImpactReview(
            id=new_id("impact"),
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            assigned_actor_id=assigned_actor_id,
            status="open",
        )
        self._session.add(review)
        self._session.flush()
        return review


def _same_dependency(reason: str, dependency_key: str) -> bool:
    """Return whether a recorded review belongs to the same dependency."""
    return f"the {dependency_key} record changed" in reason


def _permit_dependencies(snapshot: dict[str, Any]) -> list[str]:
    """Return the dependencies an issued permit recorded.

    A permit keeps the rule versions it used and the dependencies of the
    evaluation it was issued from, so that a later change can be shown to
    affect it.
    """
    dependencies = list(snapshot.get("dependencies") or [])
    rule_versions = dict((snapshot.get("evaluation") or {}).get("rule_versions") or {})
    for rule_id in rule_versions:
        dependencies.append(f"rule:{rule_id}")
    for entry in snapshot.get("rule_versions") or []:
        dependencies.append(f"rule:{str(entry).split('@', 1)[0]}")
    return dependencies


__all__ = [
    "DEFAULT_REVIEWER_ACTOR_ID",
    "AffectedCase",
    "ChangeImpactCommand",
    "ImpactService",
    "ImpactSummary",
]
