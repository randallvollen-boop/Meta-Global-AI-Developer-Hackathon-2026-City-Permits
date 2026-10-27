"""Change lifecycle, source commands, dependencies and the durable outbox."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import Base, CorrelationMixin, CreatedAtMixin, IdMixin, VersionMixin
from acme_city.persistence.types import UTCDateTime


class ChangeCase(IdMixin, VersionMixin, CorrelationMixin, CreatedAtMixin, Base):
    """Operational stewardship work with explicit ownership and state history."""

    __tablename__ = "change_cases"

    target_type: Mapped[str] = mapped_column(String(48), nullable=False)
    target_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    change_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="factual")
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    proposed_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    requester_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assignee_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    approver_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(240), nullable=True)
    expected_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="requested")
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    __table_args__ = (
        CheckConstraint(
            "change_kind IN ('factual', 'identity')", name="change_kind_allowed"
        ),
        CheckConstraint(
            "status IN ('requested', 'in_review', 'awaiting_approval', 'approved', 'sent_to_source', "
            "'source_acknowledged', 'registry_committed', 'published', 'closed', 'rejected', "
            "'synchronization_failed')",
            name="status_allowed",
        ),
    )


class SourceCommand(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """A requested change to a source system, with its expected version."""

    __tablename__ = "source_commands"

    change_case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("change_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operation: Mapped[str] = mapped_column(String(96), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retry_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    accepted_source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'timeout', 'conflict')",
            name="status_allowed",
        ),
    )


class ChangeDependency(IdMixin, CreatedAtMixin, Base):
    """A consumer that depends on a changed record."""

    __tablename__ = "change_dependencies"

    change_case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("change_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    consumer_type: Mapped[str] = mapped_column(String(48), nullable=False)
    consumer_id: Mapped[str] = mapped_column(String(96), nullable=False)
    event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    invalidation_state: Mapped[str] = mapped_column(String(32), nullable=False, default="affected")
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)


class ReviewTask(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """An assigned review task created for one dependency and event."""

    __tablename__ = "review_tasks"

    change_case_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("change_cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assignee_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(48), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    deduplication_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)


class OutboxDelivery(IdMixin, VersionMixin, CorrelationMixin, CreatedAtMixin, Base):
    """A durable publication.  Pending work survives a restart."""

    __tablename__ = "outbox_deliveries"

    change_case_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("change_cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    destination: Mapped[str] = mapped_column(String(160), nullable=False)
    payload_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retry_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dispatched_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'dispatched', 'acknowledged', 'failed')", name="status_allowed"
        ),
    )


class ConsumerAcknowledgement(IdMixin, CreatedAtMixin, Base):
    """A consumer's acknowledgement of a delivered publication."""

    __tablename__ = "consumer_acknowledgements"

    delivery_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("outbox_deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    consumer_id: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="acknowledged")
    acknowledged_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class GovernanceIssue(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """An open issue that blocks a dependent action until it is resolved."""

    __tablename__ = "governance_issues"

    subject_type: Mapped[str] = mapped_column(String(48), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    responsible_queue_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assigned_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)


__all__ = [
    "ChangeCase",
    "ChangeDependency",
    "ConsumerAcknowledgement",
    "GovernanceIssue",
    "OutboxDelivery",
    "ReviewTask",
    "SourceCommand",
]
