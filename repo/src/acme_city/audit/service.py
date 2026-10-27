"""Append-only audit writes.

An audit event is written inside the same transaction as the business change
it describes, so an accepted change and its audit record commit together or
not at all.  The service exposes no update and no delete operation: the
history is append-only through the application.
"""
# REQUIRES: SEC-04
# The audit trail is append-only through the application: there is no update and no
# delete operation, and the events carry no private record value.


from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.core.clock import utc_now
from acme_city.core.ids import new_id
from acme_city.persistence.models import audit


class AuditService:
    """Writes audit events for accepted and denied actions."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()

    def append(
        self,
        *,
        action: str,
        actor: ActorContext | str,
        target_type: str | None = None,
        target_id: str | None = None,
        before_version: int | None = None,
        after_version: int | None = None,
        reason: str | None = None,
        references: Iterable[str] = (),
        correlation_id: str | None = None,
        outcome: str = "accepted",
        denial_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> audit.AuditEvent:
        """Append one audit event and return it.

        Args:
            action: The explicit action name, for example
                ``governance.dataset.register``.
            actor: The acting actor context, or a bare actor identifier.
            target_type: The kind of record the action touched.
            target_id: The identifier of the record the action touched.
            before_version: The version before the change, when there was one.
            after_version: The version after the change, when there was one.
            reason: The recorded reason for the action.
            references: Identifiers of related records.
            correlation_id: Links the event to other records of the same action.
            outcome: ``accepted`` or ``denied``.
            denial_reason: Why the action was refused.  It never carries a
                private record value.
            metadata: Additional non-sensitive detail.
        """
        if outcome not in {"accepted", "denied"}:
            raise ValueError("audit outcome must be 'accepted' or 'denied'")
        if isinstance(actor, ActorContext):
            actor_id = actor.actor_id
            role_ids = sorted(actor.role_ids)
        else:
            actor_id = actor
            role_ids = []
        event = audit.AuditEvent(
            id=new_id("audit"),
            correlation_id=correlation_id or new_id("corr"),
            occurred_at=self._now,
            actor_id=actor_id,
            actor_role_ids=role_ids,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before_version=before_version,
            after_version=after_version,
            reason=reason,
            references=list(references),
            outcome=outcome,
            denial_reason=denial_reason,
            metadata_json=dict(metadata) if metadata else None,
        )
        self._session.add(event)
        return event

    def record_denied(
        self,
        *,
        action: str,
        actor: ActorContext | str,
        target_type: str | None = None,
        target_id: str | None = None,
        denial_reason: str,
        correlation_id: str | None = None,
    ) -> audit.AuditEvent:
        """Append a denied-action event without any private record value."""
        return self.append(
            action=action,
            actor=actor,
            target_type=target_type,
            target_id=target_id,
            outcome="denied",
            denial_reason=denial_reason,
            correlation_id=correlation_id,
        )


__all__ = ["AuditService"]
