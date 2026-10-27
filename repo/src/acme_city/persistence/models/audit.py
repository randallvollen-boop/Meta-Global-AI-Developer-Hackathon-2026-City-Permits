"""The append-only application audit trail.

Audit events are written inside the same transaction as the accepted business
change they describe.  The application exposes no update or delete path for
this table.  Denied sensitive writes are recorded without private values.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import Base, CorrelationMixin, CreatedAtMixin, IdMixin
from acme_city.persistence.types import UTCDateTime


class AuditEvent(IdMixin, CorrelationMixin, CreatedAtMixin, Base):
    """One recorded application action."""

    __tablename__ = "audit_events"

    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    actor_role_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    before_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    after_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    references: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="accepted")
    denial_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        CheckConstraint("outcome IN ('accepted', 'denied')", name="outcome_allowed"),
    )


class AuditReference(IdMixin, CreatedAtMixin, Base):
    """A reference from an audit event to another record."""

    __tablename__ = "audit_references"

    event_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("audit_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference_type: Mapped[str] = mapped_column(String(48), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(96), nullable=False)


__all__ = ["AuditEvent", "AuditReference"]
