"""Agent operations models of the agent operator lane.

The lane adds its tables here without editing the models package.  The
``agent_role_entitlements`` table is the authoritative record of which role
may wake and run the agents: the seeded grants of a persona are the default,
and this table is what the City Administrator changes when it grants or
revokes that role.

The ``agent_work_queue`` table is the durable queue of the agent work.  It
holds one row per piece of work, with a status column and an attempt count.

The ``muse_daily_budget`` table is the daily allowance of provider calls.  It
holds one row per UTC day and counts the calls that were reserved, so a call
that failed still counts and a restart does not hand out a fresh allowance.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import (
    Base,
    CorrelationMixin,
    CreatedAtMixin,
    IdMixin,
    VersionMixin,
)
from acme_city.persistence.types import UTCDateTime

#: The states a piece of queued work may hold.
WORK_PENDING = "pending"
WORK_RUNNING = "running"
WORK_COMPLETED = "completed"
WORK_FAILED = "failed"
WORK_HELD = "held"


class AgentRoleEntitlement(IdMixin, CorrelationMixin, CreatedAtMixin, VersionMixin, Base):
    """The entitlement of one role to wake and run the agents.

    One row per role.  ``can_run_agents`` is the single source of truth for
    the agent operation grants of every actor of that role, so a role change
    reaches the people who already hold the role and the people who receive
    it later.
    """

    __tablename__ = "agent_role_entitlements"

    role_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    can_run_agents: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    changed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AgentProcessingPolicy(IdMixin, CorrelationMixin, CreatedAtMixin, VersionMixin, Base):
    """The persisted manual or automatic processing policy.

    The seeded values come from ``config/demo.json``.  The columns carry the
    default of the schema, so the table is complete even before the reset
    seeds it.
    """

    __tablename__ = "agent_processing_policies"

    mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="manual")
    runs_per_hour: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    max_batch_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default="20")
    __table_args__ = (
        CheckConstraint("mode IN ('manual', 'automatic')", name="mode_allowed"),
        CheckConstraint("runs_per_hour BETWEEN 1 AND 120", name="runs_per_hour_range"),
        CheckConstraint("max_batch_size BETWEEN 1 AND 20", name="max_batch_size_range"),
    )


class AgentWorkQueue(IdMixin, CorrelationMixin, CreatedAtMixin, VersionMixin, Base):
    """One piece of work for the agents.

    The queue is the durable record of what the agents still have to do.
    One row is one piece of work for one case: ``work_key`` is its identity,
    ``status`` says where the work stands and ``attempts`` counts how often
    it was tried.  There is no lease and no fencing token.  The row itself is
    the authority, and a worker takes a piece of work by moving it from
    ``pending`` to ``running`` in one statement, so two workers never hold
    the same work.  A finish names the attempt it ends, so a late finish of
    an earlier attempt is refused.
    """

    __tablename__ = "agent_work_queue"

    work_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    application_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_key: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=WORK_PENDING, server_default=WORK_PENDING
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "agent_key IN ('intake', 'adjudication')", name="agent_key_allowed"
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'held')",
            name="status_allowed",
        ),
    )


class MuseDailyBudget(IdMixin, CreatedAtMixin, Base):
    """The provider calls the City reserved today.

    One row per UTC day.  The counter is the number of calls that were
    reserved before they were dispatched, so a call that failed or timed out
    still counts against the day.  The row is the authority: a restart reads
    the same counter and never hands out a fresh allowance.
    """

    __tablename__ = "muse_daily_budget"

    day: Mapped[str] = mapped_column(String(10), nullable=False, unique=True, index=True)
    calls_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    __table_args__ = (
        CheckConstraint("calls_used >= 0", name="calls_used_range"),
    )


__all__ = [
    "AgentProcessingPolicy",
    "AgentRoleEntitlement",
    "AgentWorkQueue",
    "MuseDailyBudget",
]
