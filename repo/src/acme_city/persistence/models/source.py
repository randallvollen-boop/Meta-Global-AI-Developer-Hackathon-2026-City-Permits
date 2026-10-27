"""Source intake objects.

Raw snapshots are preserved before any normalization.  Source update time,
effective time and receipt time are separate columns and an unknown value
stays ``NULL``: arrival time never substitutes for a business time.
"""

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import Base, CorrelationMixin, CreatedAtMixin, IdMixin
from acme_city.persistence.types import UTCDateTime


class SourceSystem(IdMixin, CreatedAtMixin, Base):
    """An incoming simulated source system or an internal component."""

    __tablename__ = "source_systems"

    source_system_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    incoming: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class IngestionRun(CorrelationMixin, CreatedAtMixin, Base):
    """One ingestion of a source dataset, with its denominators."""

    __tablename__ = "ingestion_runs"

    ingestion_run_id: Mapped[str] = mapped_column(String(64), nullable=False, primary_key=True)

    source_system_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("source_systems.source_system_id", ondelete="RESTRICT"), nullable=False
    )
    dataset_key: Mapped[str] = mapped_column(String(96), nullable=False)
    contract_id: Mapped[str | None] = mapped_column(
        String(96), ForeignKey("source_contracts.contract_id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quarantined: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unresolved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SourceSnapshot(CorrelationMixin, CreatedAtMixin, Base):
    """An immutable capture of one source record version."""

    __tablename__ = "source_snapshots"

    source_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False, primary_key=True)

    ingestion_run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("ingestion_runs.ingestion_run_id", ondelete="SET NULL"), nullable=True
    )
    source_system_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("source_systems.source_system_id", ondelete="RESTRICT"), nullable=False
    )
    source_dataset_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    source_record_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_record_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    record_status: Mapped[str] = mapped_column(String(32), nullable=False, default="accepted")
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    __table_args__ = (
        UniqueConstraint(
            "source_system_id",
            "source_dataset_id",
            "source_record_id",
            "source_record_version",
            "payload_hash",
            name="uq_source_snapshot_identity",
        ),
        CheckConstraint(
            "record_status IN ('accepted', 'unchanged', 'quarantined', 'unresolved', 'staged')",
            name="record_status_allowed",
        ),
    )


class QuarantineError(IdMixin, CreatedAtMixin, Base):
    """A field-specific validation failure for a quarantined snapshot."""

    __tablename__ = "quarantine_errors"

    source_snapshot_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("source_snapshots.source_snapshot_id", ondelete="CASCADE"), nullable=False
    )
    field_path: Mapped[str] = mapped_column(String(160), nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    responsible_queue_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")


class SourceObservation(IdMixin, CreatedAtMixin, Base):
    """A counted observation about a source dataset, with its denominator."""

    __tablename__ = "source_observations"

    source_system_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("source_systems.source_system_id", ondelete="RESTRICT"), nullable=False
    )
    dataset_key: Mapped[str] = mapped_column(String(96), nullable=False)
    ingestion_run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("ingestion_runs.ingestion_run_id", ondelete="SET NULL"), nullable=True
    )
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    numerator: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    denominator: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True)


__all__ = [
    "IngestionRun",
    "QuarantineError",
    "SourceObservation",
    "SourceSnapshot",
    "SourceSystem",
]
