"""Agent steps recorded for the intake triage pipeline.

One row per named step a triage run performs.  A step is evidence, never a
decision: it records which service identity acted, when, with what input
references and what outcome, so the permit workspace timeline and the Muse
run tab can show exactly what the agents did.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import Base, CorrelationMixin, CreatedAtMixin, IdMixin
from acme_city.persistence.types import UTCDateTime


class AgentStep(IdMixin, CorrelationMixin, CreatedAtMixin, Base):
    """One recorded step of one triage run."""

    __tablename__ = "agent_steps"

    application_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_name: Mapped[str] = mapped_column(String(64), nullable=False)
    service_identity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    inputs: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="recorded")
    outcome_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recommendation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposal_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('completed', 'needs_information', 'failed', 'skipped', 'recorded')",
            name="outcome_allowed",
        ),
    )


__all__ = ["AgentStep"]
