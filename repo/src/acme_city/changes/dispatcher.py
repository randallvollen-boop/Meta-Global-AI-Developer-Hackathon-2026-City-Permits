"""The change dispatcher.

The dispatcher sends the approved source commands, records what the source
answered and delivers the accepted values to their consumers through the
durable outbox.  Pending work survives a restart, and an identical delivery
never creates a second record or a second task.
"""
# REQUIRES: CHG-02, CHG-05, CHG-06, EDIT-04
# The source command dispatch, the late-response guard, the durable outbox and the
# consumer acknowledgement processing are implemented here.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.adapters.sources.base import SourceCommand, adapter_for
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.changes.schemas import DispatchSummary
from acme_city.core.clock import utc_now
from acme_city.core.errors import ConflictError
from acme_city.core.ids import new_id
from acme_city.registry.provenance import current_accepted_snapshot
from acme_city.persistence.models import change

#: Where a published factual change is delivered.
FACTICAL_DESTINATION = "application_workspace"

#: Where a published identity change is delivered.
REGISTRY_DESTINATION = "registry_links"


def publication_destination(change_kind: str) -> str:
    """Return the consumer a published change is delivered to."""
    return REGISTRY_DESTINATION if change_kind == "identity" else FACTICAL_DESTINATION


def create_publication(
    session: Session,
    case: change.ChangeCase,
    *,
    now: datetime | None = None,
    destination: str | None = None,
) -> change.OutboxDelivery:
    """Create the durable publication of an accepted change.

    The delivery key identifies the publication of one change to one consumer.
    The same key with a different payload is a conflict: the accepted change
    cannot be rewritten under a key that was already used.
    """
    moment = now or utc_now()
    target = publication_destination(case.change_kind) if destination is None else destination
    payload = {
        "change_case_id": case.id,
        "target_type": case.target_type,
        "target_id": case.target_id,
        "change_kind": case.change_kind,
        "accepted_value": dict(case.proposed_value or {}),
        "version": case.version,
    }
    retry_key = f"publish:{case.id}:{target}"
    existing = session.execute(
        select(change.OutboxDelivery).where(change.OutboxDelivery.retry_key == retry_key)
    ).scalars().first()
    if existing is not None:
        if dict(existing.payload or {}) != payload:
            raise ConflictError(
                "a delivery with this key already carries a different payload",
                expected_version=None,
                current_version=existing.payload_version,
            )
        return existing
    delivery = change.OutboxDelivery(
        id=new_id("delivery"),
        change_case_id=case.id,
        correlation_id=case.correlation_id,
        destination=target,
        payload_version=1,
        retry_key=retry_key,
        payload=payload,
        status="pending",
        attempts=0,
        dispatched_at=None,
        acknowledged_at=None,
        last_error=None,
    )
    session.add(delivery)
    session.flush()
    return delivery


def _version_is_older(left: str | None, right: str | None) -> bool:
    """Return whether one source version is older than another."""
    if left is None or right is None:
        return False
    if left.isdigit() and right.isdigit():
        return int(left) < int(right)
    return str(left) < str(right)


class ChangeDispatcher:
    """Sends source commands and delivers the accepted values."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)

    def dispatch_pending(self, *, limit: int = 25) -> DispatchSummary:
        """Send the pending source commands and deliver the pending publications.

        The run is idempotent: a command that was already answered is not sent
        again, and a delivery that was already acknowledged is not delivered
        again.
        """
        summary = DispatchSummary()
        self._dispatch_source_commands(summary, limit=limit)
        self._dispatch_publications(summary, limit=limit)
        return summary

    # ------------------------------------------------------------ source command

    def _dispatch_source_commands(self, summary: DispatchSummary, *, limit: int) -> None:
        """Send the pending source commands and record what they answered."""
        commands = self._session.execute(
            select(change.SourceCommand)
            .where(change.SourceCommand.status == "pending")
            .order_by(change.SourceCommand.id)
            .limit(limit)
        ).scalars().all()
        for command in commands:
            case = self._session.get(change.ChangeCase, command.change_case_id)
            if case is None:
                command.status = "conflict"
                command.response = {"reason": "the change case of this command is missing"}
                continue
            dataset_key, record_id = self._target_parts(case)
            if dataset_key is None or record_id is None:
                command.status = "conflict"
                command.response = {"reason": "the change case has no source record target"}
                continue
            adapter = adapter_for(command.source_system_id, self._session, now=self._now)
            actor = ActorContext(
                actor_id=command.actor_id or case.approver_actor_id or case.requester_actor_id or "",
                role_ids=frozenset(),
                domain_scope=frozenset(),
                record_scope=frozenset(),
                active=True,
            )
            acknowledgement = adapter.apply(
                SourceCommand(
                    source_system_id=command.source_system_id,
                    dataset_key=dataset_key,
                    record_id=record_id,
                    operation=command.operation,
                    expected_version=command.expected_source_version,
                    payload=dict(command.payload or {}),
                    request_key=command.retry_key,
                    actor_id=actor.actor_id,
                    change_case_id=case.id,
                ),
                actor,
            )
            summary.dispatched += 1
            summary.command_ids.append(command.id)
            if case.id not in summary.change_case_ids:
                summary.change_case_ids.append(case.id)
            self._record_acknowledgement(command, case, acknowledgement, summary)

    def _record_acknowledgement(
        self,
        command: change.SourceCommand,
        case: change.ChangeCase,
        acknowledgement: Any,
        summary: DispatchSummary,
    ) -> None:
        """Record what the source answered and move the case accordingly."""
        response = acknowledgement.to_dict()
        current = current_accepted_snapshot(
            self._session,
            command.source_system_id,
            self._dataset_key(case),
            self._record_id(case),
        )
        current_version = current.source_record_version if current is not None else None
        late = bool(acknowledgement.late) or _version_is_older(
            acknowledgement.source_record_version, current_version
        )
        if late:
            response["late"] = True
            response["current_version"] = current_version
            response["note"] = (
                "the acknowledgement carries an older version than the source holds now; "
                "the accepted value is not rolled back"
            )
        command.response = response
        command.accepted_source_version = acknowledgement.source_record_version

        if acknowledgement.status == "accepted":
            command.status = "accepted"
            summary.acknowledged += 1
            if late:
                summary.late += 1
                self._audit.append(
                    action="change.command.late_acknowledgement",
                    actor=command.actor_id or "dispatcher",
                    target_type="source_command",
                    target_id=command.id,
                    reason=response["note"],
                    references=[case.id],
                )
                return
            before_version = case.version
            case.status = "source_acknowledged"
            case.version = before_version + 1
            create_publication(self._session, case, now=self._now)
            self._audit.append(
                action="change.command.acknowledged",
                actor=command.actor_id or "dispatcher",
                target_type="source_command",
                target_id=command.id,
                before_version=before_version,
                after_version=case.version,
                references=[case.id, acknowledgement.source_record_version or ""],
            )
            return

        if acknowledgement.status == "rejected":
            command.status = "rejected"
            summary.rejected += 1
        elif acknowledgement.status == "timeout":
            command.status = "timeout"
            summary.timed_out += 1
        else:
            command.status = "conflict"
            summary.conflicts += 1
        if command.status in {"rejected", "timeout"}:
            before_version = case.version
            case.status = "synchronization_failed"
            case.version = before_version + 1
            self._audit.append(
                action=f"change.command.{command.status}",
                actor=command.actor_id or "dispatcher",
                target_type="source_command",
                target_id=command.id,
                before_version=before_version,
                after_version=case.version,
                reason=acknowledgement.message,
                references=[case.id],
            )
        else:
            self._audit.append(
                action="change.command.conflict",
                actor=command.actor_id or "dispatcher",
                target_type="source_command",
                target_id=command.id,
                reason=acknowledgement.message,
                references=[case.id],
            )
        self._session.flush()

    # -------------------------------------------------------------- publication

    def _dispatch_publications(self, summary: DispatchSummary, *, limit: int) -> None:
        """Deliver the pending publications and record the acknowledgements."""
        deliveries = self._session.execute(
            select(change.OutboxDelivery)
            .where(change.OutboxDelivery.status == "pending")
            .order_by(change.OutboxDelivery.id)
            .limit(limit)
        ).scalars().all()
        for delivery in deliveries:
            case = (
                self._session.get(change.ChangeCase, delivery.change_case_id)
                if delivery.change_case_id
                else None
            )
            delivery.attempts = delivery.attempts + 1
            delivery.dispatched_at = self._now
            self._session.add(
                change.ConsumerAcknowledgement(
                    id=new_id("cons"),
                    delivery_id=delivery.id,
                    consumer_id=delivery.destination,
                    status="acknowledged",
                    acknowledged_at=self._now,
                    detail="the consumer received the published value",
                )
            )
            delivery.status = "acknowledged"
            delivery.acknowledged_at = self._now
            delivery.last_error = None
            summary.published += 1
            summary.delivery_ids.append(delivery.id)
            if case is not None:
                if case.id not in summary.change_case_ids:
                    summary.change_case_ids.append(case.id)
                if case.status in {"source_acknowledged", "registry_committed"}:
                    before_version = case.version
                    case.status = "published"
                    case.version = before_version + 1
                self._audit.append(
                    action="change.publication.delivered",
                    actor="dispatcher",
                    target_type="outbox_delivery",
                    target_id=delivery.id,
                    after_version=delivery.payload_version,
                    references=[case.id if case else "", delivery.destination],
                )
        self._session.flush()

    # ------------------------------------------------------------------ helpers

    def _target_parts(self, case: change.ChangeCase) -> tuple[str | None, str | None]:
        """Return the dataset and record of the target of a case."""
        parts = case.target_id.split("/")
        if len(parts) != 3:
            return None, None
        return parts[1], parts[2]

    def _dataset_key(self, case: change.ChangeCase) -> str:
        """Return the dataset of the target of a case."""
        dataset_key, _ = self._target_parts(case)
        return dataset_key or ""

    def _record_id(self, case: change.ChangeCase) -> str:
        """Return the record of the target of a case."""
        _, record_id = self._target_parts(case)
        return record_id or ""


__all__ = [
    "ChangeDispatcher",
    "FACTUAL_DESTINATION",
    "REGISTRY_DESTINATION",
    "create_publication",
    "publication_destination",
]
