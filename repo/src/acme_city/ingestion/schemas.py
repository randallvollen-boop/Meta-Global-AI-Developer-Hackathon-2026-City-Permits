"""Command and view models for source intake.

A client never sends authority with a record: the actor comes from the
server-held session and the dataset registration comes from the server.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IngestionModel(BaseModel):
    """A model that ignores unknown request fields.

    A client-supplied actor, role or permission field is ignored rather than
    honoured: the server resolves the actor and its grants.
    """

    model_config = ConfigDict(extra="ignore")


class SourceRecordCommand(IngestionModel):
    """One source record version as the source delivered it.

    The payload is the raw record.  The envelope carries the source update
    time, the business effective window and the receipt time; they stay
    separate and an unknown time stays ``None``.
    """

    source_record_id: str
    source_record_version: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    source_updated_at: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    received_at: datetime | None = None
    scenario_id: str | None = None


class IngestCommand(IngestionModel):
    """A batch of source records for one registered dataset.

    The source system and the dataset may be named in the path; the values in
    the body are only used when the caller sends them.
    """

    source_system_id: str = ""
    dataset_key: str = ""
    records: list[SourceRecordCommand] = Field(default_factory=list)
    received_at: datetime | None = None
    correlation_id: str | None = None
    scenario_id: str | None = None


class SourceRecordWriteCommand(IngestionModel):
    """A write to one record of a simulated source system.

    The write carries the version the caller expects the record to hold.  A
    write against a different version is refused as a conflict.
    """

    dataset_key: str
    record_id: str
    operation: str = "update"
    expected_version: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    request_key: str = ""


class FieldErrorView(IngestionModel):
    """One field-level validation failure."""

    field_path: str
    error_code: str
    message: str


class RecordOutcomeView(IngestionModel):
    """What happened to one source record inside a batch."""

    source_record_id: str
    source_record_version: str | None = None
    status: str = "accepted"
    source_snapshot_id: str | None = None
    payload_hash: str = ""
    field_errors: list[FieldErrorView] = Field(default_factory=list)
    issue_id: str | None = None


class IngestResult(IngestionModel):
    """The result of one intake batch, with its denominators.

    ``received`` is the denominator.  Every other counter partitions it, so
    ``accepted + unchanged + quarantined + unresolved + staged == received``.
    """

    ingestion_run_id: str
    source_system_id: str
    dataset_key: str
    registered: bool = False
    publishable: bool = False
    received: int = 0
    accepted: int = 0
    unchanged: int = 0
    quarantined: int = 0
    unresolved: int = 0
    staged: int = 0
    snapshot_ids: list[str] = Field(default_factory=list)
    field_errors: list[FieldErrorView] = Field(default_factory=list)
    records: list[RecordOutcomeView] = Field(default_factory=list)
    issue_ids: list[str] = Field(default_factory=list)
    received_at: datetime
    correlation_id: str = ""


class SourceSnapshotView(IngestionModel):
    """One preserved raw snapshot, as the intake reports it."""

    source_snapshot_id: str
    source_system_id: str
    source_dataset_id: str
    source_record_id: str
    source_record_version: str | None = None
    source_updated_at: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    ingested_at: datetime
    payload_hash: str
    record_status: str = "accepted"
    scenario_id: str | None = None
    raw_payload: dict[str, Any] | None = None


class SourceObservationView(IngestionModel):
    """One counted observation about a source dataset."""

    observation_id: str
    source_system_id: str
    dataset_key: str
    ingestion_run_id: str | None = None
    metric: str
    numerator: int = 0
    denominator: int = 0
    observed_at: datetime
    source_updated_at: datetime | None = None
    received_at: datetime
    scenario_id: str | None = None


class QuarantineErrorView(IngestionModel):
    """One field-level failure recorded against a quarantined snapshot."""

    error_id: str
    source_snapshot_id: str
    field_path: str
    error_code: str
    message: str
    responsible_queue_id: str | None = None
    status: str = "open"


__all__ = [
    "FieldErrorView",
    "IngestCommand",
    "IngestResult",
    "IngestionModel",
    "QuarantineErrorView",
    "RecordOutcomeView",
    "SourceObservationView",
    "SourceRecordCommand",
    "SourceRecordWriteCommand",
    "SourceSnapshotView",
]
