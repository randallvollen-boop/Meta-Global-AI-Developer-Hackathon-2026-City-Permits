"""The source intake endpoints.

Every endpoint resolves the actor from the server-held session.  A request
body never carries authority, and the dataset registration always comes from
the server.
"""
# REQUIRES: ING-01, ING-05, EDIT-01
# The intake endpoints report the denominators of a run, the preserved raw
# snapshots, the recorded field errors and the counted source observations.

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.adapters.sources.base import SourceCommand, adapter_for, available_adapters
from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_actor, get_internal_reader, get_session
from acme_city.core.errors import ValidationError
from acme_city.ingestion.schemas import (
    MAX_INGEST_RECORDS,
    MAX_RECORD_PAYLOAD_BYTES,
    IngestCommand,
    QuarantineErrorView,
    SourceObservationView,
    SourceRecordWriteCommand,
    SourceSnapshotView,
)
from acme_city.ingestion.service import IngestionService
from acme_city.persistence.models import source


def enforce_payload_limit(payload: dict, *, where: str) -> None:
    """Refuse a record payload that is larger than one source record may be."""
    if len(json.dumps(payload, default=str).encode("utf-8")) > MAX_RECORD_PAYLOAD_BYTES:
        raise ValidationError(
            f"{where} is larger than {MAX_RECORD_PAYLOAD_BYTES} bytes; split or trim it"
        )


router = APIRouter(prefix="/api/sources", tags=["sources"])


def ingestion_service(session: Session) -> IngestionService:
    """Return an ingestion service bound to the request session."""
    return IngestionService(session)


@router.get("/systems", operation_id="list_source_systems")
def list_source_systems(
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_internal_reader),
) -> dict:
    """List the simulated source systems and the internal components."""
    rows = session.execute(
        select(source.SourceSystem).order_by(source.SourceSystem.source_system_id)
    ).scalars().all()
    adapters = {}
    for source_system_id in available_adapters():
        adapter = adapter_for(source_system_id, session)
        adapters[source_system_id] = {
            "source_system_id": source_system_id,
            "label": adapter.label,
            "simulated": True,
            "dataset_keys": list(adapter.dataset_keys),
        }
    return {
        "source_systems": [
            {
                "source_system_id": row.source_system_id,
                "label": row.label,
                "simulated": row.simulated,
                "incoming": row.incoming,
                "description": row.description,
            }
            for row in rows
        ],
        "adapters": [adapters[key] for key in sorted(adapters)],
    }


@router.post("/{source_system_id}/records", operation_id="write_source_record")
def write_source_record(
    source_system_id: str,
    command: SourceRecordWriteCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Write a new version of a record of a simulated source system.

    The write needs the ``source.record.update`` grant and the version the
    caller expects the record to hold.  The source answers with an explicit
    acknowledgement: accepted, rejected, timeout or conflict.
    """
    enforce_payload_limit(command.payload, where="the record payload")
    adapter = adapter_for(source_system_id, session)
    acknowledgement = adapter.apply(
        SourceCommand(
            source_system_id=source_system_id,
            dataset_key=command.dataset_key,
            record_id=command.record_id,
            operation=command.operation,
            expected_version=command.expected_version,
            payload=dict(command.payload),
            request_key=command.request_key,
            actor_id=actor.actor_id,
        ),
        actor,
    )
    return acknowledgement.to_dict()


@router.post("/{source_system_id}/{dataset_key}/intake", operation_id="ingest_source_records")
def ingest_source_records(
    source_system_id: str,
    dataset_key: str,
    command: IngestCommand,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Ingest a batch of source records and report the run denominators."""
    if len(command.records) > MAX_INGEST_RECORDS:
        raise ValidationError(
            f"an intake request carries at most {MAX_INGEST_RECORDS} records; "
            f"this one carries {len(command.records)}"
        )
    for record in command.records:
        enforce_payload_limit(record.payload, where="a record payload")
    payload = command.model_copy(
        update={"source_system_id": source_system_id, "dataset_key": dataset_key}
    )
    service = ingestion_service(session)
    result = service.ingest(payload, actor)
    return result.model_dump(mode="json")


@router.get(
    "/{source_system_id}/{dataset_key}/snapshots", operation_id="list_source_snapshots"
)
def list_source_snapshots(
    source_system_id: str,
    dataset_key: str,
    record_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_internal_reader),
) -> dict:
    """List the preserved raw snapshots of a dataset."""
    statement = select(source.SourceSnapshot).where(
        source.SourceSnapshot.source_system_id == source_system_id,
        source.SourceSnapshot.source_dataset_id == dataset_key,
    )
    if record_id:
        statement = statement.where(source.SourceSnapshot.source_record_id == record_id)
    if status:
        statement = statement.where(source.SourceSnapshot.record_status == status)
    rows = session.execute(
        statement.order_by(
            source.SourceSnapshot.ingested_at, source.SourceSnapshot.source_snapshot_id
        ).limit(limit)
    ).scalars().all()
    views = [
        SourceSnapshotView(
            source_snapshot_id=row.source_snapshot_id,
            source_system_id=row.source_system_id,
            source_dataset_id=row.source_dataset_id,
            source_record_id=row.source_record_id,
            source_record_version=row.source_record_version,
            source_updated_at=row.source_updated_at,
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            ingested_at=row.ingested_at,
            payload_hash=row.payload_hash,
            record_status=row.record_status,
            scenario_id=row.scenario_id,
            raw_payload=row.raw_payload,
        )
        for row in rows
    ]
    return {"snapshots": [view.model_dump(mode="json") for view in views]}


@router.get(
    "/{source_system_id}/{dataset_key}/observations", operation_id="list_source_observations"
)
def list_source_observations(
    source_system_id: str,
    dataset_key: str,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_internal_reader),
) -> dict:
    """List the counted observations of a dataset with their denominators."""
    rows = session.execute(
        select(source.SourceObservation)
        .where(
            source.SourceObservation.source_system_id == source_system_id,
            source.SourceObservation.dataset_key == dataset_key,
        )
        .order_by(source.SourceObservation.observed_at, source.SourceObservation.id)
        .limit(limit)
    ).scalars().all()
    views = [
        SourceObservationView(
            observation_id=row.id,
            source_system_id=row.source_system_id,
            dataset_key=row.dataset_key,
            ingestion_run_id=row.ingestion_run_id,
            metric=row.metric,
            numerator=row.numerator,
            denominator=row.denominator,
            observed_at=row.observed_at,
            source_updated_at=row.source_updated_at,
            received_at=row.received_at,
            scenario_id=row.scenario_id,
        )
        for row in rows
    ]
    return {"observations": [view.model_dump(mode="json") for view in views]}


@router.get(
    "/{source_system_id}/{dataset_key}/quarantine", operation_id="list_source_quarantine_errors"
)
def list_source_quarantine_errors(
    source_system_id: str,
    dataset_key: str,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_internal_reader),
) -> dict:
    """List the recorded field errors of the quarantined records of a dataset."""
    rows = session.execute(
        select(source.QuarantineError)
        .join(
            source.SourceSnapshot,
            source.SourceSnapshot.source_snapshot_id == source.QuarantineError.source_snapshot_id,
        )
        .where(
            source.SourceSnapshot.source_system_id == source_system_id,
            source.SourceSnapshot.source_dataset_id == dataset_key,
        )
        .order_by(source.QuarantineError.id)
        .limit(limit)
    ).scalars().all()
    views = [
        QuarantineErrorView(
            error_id=row.id,
            source_snapshot_id=row.source_snapshot_id,
            field_path=row.field_path,
            error_code=row.error_code,
            message=row.message,
            responsible_queue_id=row.responsible_queue_id,
            status=row.status,
        )
        for row in rows
    ]
    return {"quarantine_errors": [view.model_dump(mode="json") for view in views]}


__all__ = ["ingestion_service", "router"]
