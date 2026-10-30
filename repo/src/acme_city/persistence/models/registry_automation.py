"""Durable policy, work, evidence, and review state for registry automation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import Base, CreatedAtMixin, IdMixin, VersionMixin
from acme_city.persistence.types import UTCDateTime


class RegistryAutomationPolicy(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """One immutable version of steward-approved auto-link policy."""

    __tablename__ = "registry_automation_policies"

    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="paused", server_default="paused")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", server_default="draft")
    matcher_version: Mapped[str] = mapped_column(String(64), nullable=False)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_scopes: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_by_actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    __table_args__ = (
        CheckConstraint("mode IN ('paused', 'suggestions', 'active')", name="mode_allowed"),
        CheckConstraint("status IN ('draft', 'active', 'superseded')", name="status_allowed"),
    )


class RegistryAutomationJob(IdMixin, CreatedAtMixin, Base):
    """Durable work for one accepted source version and target family.

    The row follows the runtime contract of the agents: one status column, an
    attempt count and no lease.  A worker takes the job by moving it from
    ``pending`` to ``running`` in a single statement, and only the worker that
    won that statement may finish it.
    """

    __tablename__ = "registry_automation_jobs"

    source_snapshot_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("source_snapshots.source_snapshot_id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    target_family: Mapped[str] = mapped_column(String(48), nullable=False)
    matcher_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("registry_automation_policies.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    available_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        UniqueConstraint(
            "source_snapshot_id", "target_family", "matcher_version", "policy_id",
            name="uq_registry_automation_job_evaluation_key",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'needs_review')",
            name="status_allowed",
        ),
    )


class RegistryAutomationEvaluation(IdMixin, CreatedAtMixin, Base):
    """Immutable candidate-specific evidence produced for one job."""

    __tablename__ = "registry_automation_evaluations"

    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("registry_automation_jobs.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    source_snapshot_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("source_snapshots.source_snapshot_id", ondelete="RESTRICT"),
        nullable=False
    )
    policy_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("registry_automation_policies.id", ondelete="SET NULL"), nullable=True
    )
    target_family: Mapped[str] = mapped_column(String(48), nullable=False)
    target_entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_scale: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (
        CheckConstraint("decision IN ('auto_apply', 'suggest', 'ignore')", name="decision_allowed"),
    )


class RegistryAutomationApplication(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """Reviewable result of an automatically applied registry link."""

    __tablename__ = "registry_automation_applications"

    evaluation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("registry_automation_evaluations.id", ondelete="RESTRICT"),
        nullable=False, unique=True
    )
    crosswalk_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("crosswalks.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="applied", server_default="applied")
    before_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    after_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    applied_by_actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    reviewed_by_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "status IN ('applied', 'acknowledged', 'reversed', 'superseded')",
            name="status_allowed",
        ),
    )


__all__ = [
    "RegistryAutomationApplication",
    "RegistryAutomationEvaluation",
    "RegistryAutomationJob",
    "RegistryAutomationPolicy",
]
