"""The recommendation the steward assistant prepares for a task of the queue.

One row is one recommendation: what the assistant proposes, how sure it is,
the evidence it read, the words the steward reads and the version of the
record it read.  A recommendation never decides anything: the steward accepts
it, changes it, ignores it or clears it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import Base, CreatedAtMixin, IdMixin, VersionMixin
from acme_city.persistence.types import UTCDateTime


class StewardRecommendation(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """One recommendation the assistant prepared for one task of the queue.

    The row is a preparation, never a decision.  ``record_version`` is the
    version of the record the recommendation read, so a record that changed
    since can be recognized as stale before anything is accepted.
    """

    __tablename__ = "steward_recommendations"

    #: The kind of the task: ``link``, ``automatic_link``, ``parcel``, ``case``
    #: or ``issue``.
    task_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The identifier of the task inside its kind.
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: The version of the record the recommendation read.
    record_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    #: What the assistant proposes the steward does.
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    #: How sure the assistant is: ``high``, ``review`` or ``held``.
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The evidence the recommendation was built from.
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    #: The plain words the steward reads.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    #: The plain words Muse wrote for the reason, when the steward asked for
    #: them.  The deterministic reason of the assistant stays the reason of
    #: the recommendation: Muse rewrites the words, never the decision.
    muse_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The recorded model run that wrote the plain words.
    muse_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The actor that made the recommendation.
    made_by_actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The moment the recommendation was made.
    made_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    #: True when the recommendation is no longer shown.
    cleared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    #: The moment the recommendation was cleared.
    cleared_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "confidence IN ('high', 'review', 'held')",
            name="confidence_allowed",
        ),
        CheckConstraint(
            "outcome IN ('confirm', 'reject', 'ask_source', 'keep', 'undo', "
            "'approve_parcel', 'none_fits', 'accept', 'resolve', 'awaiting_source')",
            name="outcome_allowed",
        ),
    )


__all__ = [
    "StewardRecommendation",
]
