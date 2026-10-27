"""Agent controls, agent runs and the recorded steps of a run.

An ``agent_controls`` row is the awake/asleep state of one agent.  An
``agent_run`` row is one run of one agent on one application, and its
``agent_run_nodes`` rows are the per-node trace of that run.  The recorded
``agent_steps`` remain the per-step evidence of the pipeline.

A run is evidence, never a decision: it records which service identity acted,
when, at whose request, with what outcome, so the permit workspace timeline and
the agent screens can show exactly what the agents did.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import (
    Base,
    CorrelationMixin,
    CreatedAtMixin,
    IdMixin,
    VersionMixin,
)
from acme_city.persistence.types import UTCDateTime

#: The two agents of the demonstration.  Agents are service identities, never
#: selectable personas.
AGENT_INTAKE = "intake"
AGENT_ADJUDICATION = "adjudication"

#: The modes an agent may hold.
AGENT_ASLEEP = "asleep"
AGENT_AWAKE = "awake"


class AgentControl(IdMixin, CorrelationMixin, CreatedAtMixin, VersionMixin, Base):
    """The awake/asleep state of one agent."""

    __tablename__ = "agent_controls"

    agent_key: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default=AGENT_ASLEEP)
    changed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    __table_args__ = (
        CheckConstraint("mode IN ('asleep', 'awake')", name="mode_allowed"),
    )


class AgentRun(IdMixin, CorrelationMixin, CreatedAtMixin, Base):
    """One run of one agent on one application."""

    __tablename__ = "agent_runs"

    agent_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    application_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    service_identity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    triggered_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="recorded")
    outcome_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    inputs: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "agent_key IN ('intake', 'adjudication')",
            name="agent_key_allowed",
        ),
        CheckConstraint(
            "outcome IN ('completed', 'needs_information', 'recommended', 'held', "
            "'failed', 'skipped', 'recorded')",
            name="outcome_allowed",
        ),
    )


class AgentRunNode(IdMixin, CreatedAtMixin, Base):
    """One node of the dependency graph of one agent run."""

    __tablename__ = "agent_run_nodes"

    agent_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    dependency_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'warn', 'block')", name="status_allowed"),
    )


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


__all__ = [
    "AGENT_ADJUDICATION",
    "AGENT_AWAKE",
    "AGENT_ASLEEP",
    "AGENT_INTAKE",
    "AgentControl",
    "AgentRun",
    "AgentRunNode",
    "AgentStep",
]
