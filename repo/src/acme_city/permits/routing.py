"""Routing metadata of a permit application.

Two pieces of routing metadata sit on a case: its **priority** (``normal``
or ``high``) and its **owner** (the staff member the case is routed to).

The owner is routing metadata only.  An owner gains no authority, is never
a decision maker because of the assignment, and never becomes a selectable
persona: the four selectable personas stay exactly four.  The eligible
owners of a case are the active people eligible for the stage of the case:
a steward-capable person for an intake case, a reviewer-capable person for
a case in review.
"""
# REQUIRES: PER-03, SEC-02
# The priority and the owner of a case are governed, audited, version-checked
# routing metadata; an assignment grants nothing.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.permits.guard import require_mutable
from acme_city.persistence.models import governance, permit

#: The grants the routing actions need.
PERMISSION_PRIORITY = "permit.case.priority"
PERMISSION_ASSIGN = "permit.case.assign"

#: The domain every permit action is authorized in.
PERMIT_DOMAIN = "permits"

#: The priorities a case may carry.
PRIORITIES: tuple[str, ...] = ("normal", "high")

#: The statuses a case may hold when it is routed to an intake owner.
INTAKE_STAGE_STATUSES: frozenset[str] = frozenset(
    {"submitted", "needs_information", "revisions_requested"}
)

#: The statuses a case may hold when it is routed to a review owner.
REVIEW_STAGE_STATUSES: frozenset[str] = frozenset({"ready_for_review", "under_review"})

#: The grant that marks a person as eligible to own an intake case.
INTAKE_OWNER_GRANT = "permit.case.advance"

#: The grant that marks a person as eligible to own a review case.
REVIEW_OWNER_GRANT = "permit.decide"


def stage_of(application: permit.Application) -> str | None:
    """Return the stage a case is routed at, if it is routed at all."""
    if application.status in INTAKE_STAGE_STATUSES:
        return "intake"
    if application.status in REVIEW_STAGE_STATUSES:
        return "review"
    return None


class RoutingService:
    """The priority and the owner of an application."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    def set_priority(
        self,
        *,
        application_id: str,
        priority: str,
        actor: ActorContext,
        expected_version: int | None,
    ) -> permit.Application:
        """Change the priority of a case.

        The intake agent records the priority the intake record carried; a
        Data Steward may change it afterwards.
        """
        application = self._load_for_action(
            application_id,
            actor,
            PERMISSION_PRIORITY,
            expected_version,
            action="changing the priority",
        )
        clean = str(priority or "").strip().lower()
        if clean not in PRIORITIES:
            raise ValidationError(
                "a priority is " + " or ".join(PRIORITIES) + "; use one of those"
            )
        before = application.priority
        application.priority = clean
        application.version += 1
        self._session.flush()
        self._record_action(
            application=application,
            action="set_priority",
            actor=actor,
            metadata={"priority_before": before, "priority_after": clean},
        )
        return application

    def assign(
        self,
        *,
        application_id: str,
        owner_actor_id: str,
        actor: ActorContext,
        expected_version: int | None,
    ) -> permit.Application:
        """Route a case to a staff member.

        The owner must be an active person eligible for the stage of the
        case.  A service identity is never eligible: it is not a person.
        """
        application = self._load_for_action(
            application_id,
            actor,
            PERMISSION_ASSIGN,
            expected_version,
            action="assigning the application",
        )
        stage = stage_of(application)
        if stage is None:
            raise ValidationError(
                f"an application in status {application.status!r} is not routed to a person"
            )
        owner_id = str(owner_actor_id or "").strip()
        if not owner_id:
            raise ValidationError("an assignment needs an owner")
        eligible = self.eligible_owners(stage)
        if owner_id not in {entry["actor_id"] for entry in eligible}:
            raise ValidationError(
                "that person is not an active person eligible to own a case at this stage"
            )
        before = application.owner_actor_id
        application.owner_actor_id = owner_id
        application.version += 1
        self._session.flush()
        self._record_action(
            application=application,
            action="assign",
            actor=actor,
            metadata={
                "owner_before": before or "",
                "owner_after": owner_id,
                "stage": stage,
            },
        )
        return application

    def eligible_owners(self, stage: str) -> list[dict[str, Any]]:
        """Return the active people eligible to own a case at a stage."""
        capability = INTAKE_OWNER_GRANT if stage == "intake" else REVIEW_OWNER_GRANT
        resolver = PermissionResolver(self._session, now=self._now)
        rows = self._session.execute(
            select(governance.Actor).where(
                governance.Actor.active.is_(True),
                or_(
                    governance.Actor.selectable.is_(True),
                    governance.Actor.persona_role.is_not(None),
                ),
            )
        ).scalars().all()
        eligible: list[dict[str, Any]] = []
        for row in rows:
            if capability not in resolver.permissions_for(row.actor_id):
                continue
            eligible.append(
                {
                    "actor_id": row.actor_id,
                    "label": row.label,
                    "department": row.department or "",
                    "stage": stage,
                }
            )
        eligible.sort(key=lambda entry: entry["label"])
        return eligible

    # ------------------------------------------------------------- internals

    def _load_for_action(
        self,
        application_id: str,
        actor: ActorContext,
        permission: str,
        expected_version: int | None,
        *,
        action: str,
    ) -> permit.Application:
        """Load the application of an action and check it may happen."""
        application = self._session.execute(
            select(permit.Application).where(permit.Application.id == application_id)
        ).scalar_one_or_none()
        if application is None:
            raise NotFoundError("that application does not exist")
        self._permissions.authorize(
            actor,
            permission,
            ResourceContext(
                domain_id=PERMIT_DOMAIN,
                record_ids=(
                    application.source_application_number,
                    application.applicant_party_id or "",
                ),
            ),
        )
        if expected_version is None:
            raise ValidationError(f"an expected version is required to {action}")
        if application.version != expected_version:
            raise ValidationError(
                "the application changed since it was read; read it again and retry"
            )
        require_mutable(application, action=action)
        return application

    def _record_action(
        self,
        *,
        application: permit.Application,
        action: str,
        actor: ActorContext,
        metadata: dict[str, Any] | None = None,
    ) -> permit.ApplicationAction:
        """Record one routing action and its audit event."""
        row = permit.ApplicationAction(
            id=new_id("appaction"),
            correlation_id=application.correlation_id or new_id("corr"),
            application_id=application.id,
            action=action,
            actor_id=actor.actor_id,
            occurred_at=self._now,
            metadata_json=dict(metadata) if metadata else None,
        )
        self._session.add(row)
        self._session.flush()
        self._audit.append(
            action=f"application.{action}",
            actor=actor,
            target_type="application",
            target_id=application.id,
            after_version=application.version,
            references=[row.id],
            correlation_id=row.correlation_id,
            metadata={"action": action, "detail": dict(metadata) if metadata else {}},
        )
        self._session.flush()
        return row


__all__ = [
    "INTAKE_OWNER_GRANT",
    "INTAKE_STAGE_STATUSES",
    "PERMISSION_ASSIGN",
    "PERMISSION_PRIORITY",
    "PRIORITIES",
    "REVIEW_OWNER_GRANT",
    "REVIEW_STAGE_STATUSES",
    "RoutingService",
    "stage_of",
]
