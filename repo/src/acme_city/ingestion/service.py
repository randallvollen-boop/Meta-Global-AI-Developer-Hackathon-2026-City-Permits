"""Registered source intake.

The intake preserves the raw payload before it validates anything, keeps the
source update time, the business effective window and the receipt time apart,
and refuses to let an older arrival replace a newer accepted value.
"""
# REQUIRES: ING-01, ING-02, ING-03, ING-04, ING-05, GOV-01, D10
# Raw payload preservation, contract-driven validation, idempotent ingestion keys,
# separate source/effective/receipt times, accurate denominators and the
# unowned-feed staging gate are implemented here.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import ValidationError
from acme_city.core.ids import new_id
from acme_city.fixtures.loader import payload_hash
from acme_city.governance.service import GovernanceService
from acme_city.ingestion.schemas import (
    FieldErrorView,
    IngestCommand,
    IngestResult,
    RecordOutcomeView,
)
from acme_city.ingestion.validation import (
    CONTROL_FIELD_NAME,
    FieldError,
    PayloadValidator,
    intake_rules_for,
)
from acme_city.persistence.models import change, governance, source

#: The metric names the intake reports, one per denominator.
OBSERVATION_METRICS: tuple[str, ...] = (
    "records_received",
    "records_accepted",
    "records_unchanged",
    "records_quarantined",
    "records_unresolved",
    "records_staged",
)

#: The status of a record that is preserved as history but is not the current
#: accepted value.
HISTORY_STATUS = "unresolved"

#: The identity that the cross-domain governance routing identity owns.
GOVERNANCE_ROUTING_ACTOR_ID = "service_governance_lead"


def _require_aware(value: datetime | None, field_name: str) -> None:
    """Refuse a timestamp without a timezone.

    An unknown time stays ``None``; a known time is always timezone-aware.
    """
    if value is not None and value.tzinfo is None:
        raise ValidationError(
            f"{field_name} must be timezone-aware; an unknown time is left empty"
        )


def _numeric_version(value: str | None) -> int | None:
    """Return a numeric source version, when the source delivered one."""
    if value is None:
        return None
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return None


def _is_older(
    incoming_version: str | None,
    incoming_updated_at: datetime | None,
    current_version: str | None,
    current_updated_at: datetime | None,
) -> bool:
    """Return whether an incoming record is older than the accepted one.

    The source version decides when both sides carry a numeric version.  A
    source that versions its records some other way falls back to the source
    update time, and the effective time is the last resort.  An arrival that
    cannot be ordered is never treated as older.
    """
    incoming_number = _numeric_version(incoming_version)
    current_number = _numeric_version(current_version)
    if incoming_number is not None and current_number is not None:
        return incoming_number < current_number
    if incoming_updated_at is not None and current_updated_at is not None:
        return incoming_updated_at < current_updated_at
    return False


class IngestionService:
    """Ingests source records into the registry's raw and trusted layers."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)
        self._governance = GovernanceService(session, now=self._now)

    # ------------------------------------------------------------------ helpers

    def contract_for(
        self, source_system_id: str, dataset_key: str
    ) -> governance.SourceContract | None:
        """Return the registered contract of a dataset, when it has one."""
        return self._session.execute(
            select(governance.SourceContract).where(
                governance.SourceContract.source_system_id == source_system_id,
                governance.SourceContract.dataset_key == dataset_key,
            )
        ).scalar_one_or_none()

    def current_accepted_snapshot(
        self, source_system_id: str, dataset_key: str, record_id: str
    ) -> source.SourceSnapshot | None:
        """Return the accepted snapshot of a source record with the newest version."""
        rows = self._session.execute(
            select(source.SourceSnapshot).where(
                source.SourceSnapshot.source_system_id == source_system_id,
                source.SourceSnapshot.source_dataset_id == dataset_key,
                source.SourceSnapshot.source_record_id == record_id,
                source.SourceSnapshot.record_status == "accepted",
            )
        ).scalars().all()
        if not rows:
            return None
        return max(
            rows,
            key=lambda row: (
                _numeric_version(row.source_record_version)
                if _numeric_version(row.source_record_version) is not None
                else -1,
                row.source_updated_at is not None,
                row.source_updated_at or row.ingested_at,
            ),
        )

    def reference_exists(self, source_system_id: str, dataset_key: str, record_id: str) -> bool:
        """Return whether a source record is known inside its own source system."""
        found = self._session.execute(
            select(source.SourceSnapshot.source_snapshot_id).where(
                source.SourceSnapshot.source_system_id == source_system_id,
                source.SourceSnapshot.source_dataset_id == dataset_key,
                source.SourceSnapshot.source_record_id == record_id,
                source.SourceSnapshot.record_status == "accepted",
            )
        ).first()
        return found is not None

    def snapshot_by_identity(
        self,
        source_system_id: str,
        dataset_key: str,
        record_id: str,
        record_version: str | None,
        hash_value: str,
    ) -> source.SourceSnapshot | None:
        """Return the snapshot that carries one exact ingestion identity."""
        return self._session.execute(
            select(source.SourceSnapshot).where(
                source.SourceSnapshot.source_system_id == source_system_id,
                source.SourceSnapshot.source_dataset_id == dataset_key,
                source.SourceSnapshot.source_record_id == record_id,
                source.SourceSnapshot.source_record_version == record_version,
                source.SourceSnapshot.payload_hash == hash_value,
            )
        ).scalar_one_or_none()

    # ------------------------------------------------------------------- intake

    def ingest(self, command: IngestCommand, actor: ActorContext) -> IngestResult:
        """Ingest one batch of source records.

        Args:
            command: The batch.  It carries the source system, the dataset and
                the records as the source delivered them.
            actor: The acting actor, resolved from the server-held session.

        Returns:
            The result of the batch, with the denominators of the run.
        """
        contract = self.contract_for(command.source_system_id, command.dataset_key)
        domain_id = contract.domain_id if contract is not None else None
        self._permissions.authorize(
            actor,
            "source.snapshot.stage",
            ResourceContext(
                domain_id=domain_id,
                record_type="source_dataset",
                record_ids=(command.dataset_key,),
            ),
        )
        if contract is not None and contract.source_system_id != command.source_system_id:
            raise ValidationError("the contract does not belong to the stated source system")
        if not command.records:
            raise ValidationError("an intake batch must carry at least one record")

        missing_bindings = (
            self._governance.missing_bindings(contract) if contract is not None else ["contract"]
        )
        registered = contract is not None and not missing_bindings
        publishable = registered and contract.registration_state == "complete"

        received_at = command.received_at or self._now
        correlation_id = command.correlation_id or new_id("corr")
        run = source.IngestionRun(
            ingestion_run_id=new_id("inrun"),
            correlation_id=correlation_id,
            source_system_id=command.source_system_id,
            dataset_key=command.dataset_key,
            contract_id=contract.contract_id if contract is not None else None,
            started_at=self._now,
            completed_at=None,
            received=0,
            accepted=0,
            unchanged=0,
            quarantined=0,
            unresolved=0,
            status="running",
            notes=None,
        )
        self._session.add(run)
        self._session.flush()

        accepted_ids: set[str] = set()
        outcomes: list[RecordOutcomeView] = []
        snapshot_ids: list[str] = []
        all_errors: list[FieldErrorView] = []
        issue_ids: list[str] = []
        counters = {
            "accepted": 0,
            "unchanged": 0,
            "quarantined": 0,
            "unresolved": 0,
            "staged": 0,
        }
        latest_source_update: datetime | None = None

        for record in command.records:
            outcome, errors, issue_id = self._ingest_record(
                run=run,
                contract=contract,
                command=command,
                record=record,
                received_at=received_at,
                correlation_id=correlation_id,
                registered=registered,
                publishable=publishable,
                accepted_ids=accepted_ids,
            )
            outcomes.append(outcome)
            snapshot_ids.append(outcome.source_snapshot_id or "")
            all_errors.extend(errors)
            counters[outcome.status] = counters.get(outcome.status, 0) + 1
            if issue_id:
                issue_ids.append(issue_id)
            if record.source_updated_at is not None and (
                latest_source_update is None or record.source_updated_at > latest_source_update
            ):
                latest_source_update = record.source_updated_at

        run.received = len(command.records)
        run.accepted = counters["accepted"]
        run.unchanged = counters["unchanged"]
        run.quarantined = counters["quarantined"]
        run.unresolved = counters["unresolved"]
        run.status = "completed"
        run.completed_at = self._now
        self._session.flush()

        self._record_observations(
            run=run,
            command=command,
            counters=counters,
            received_at=received_at,
            latest_source_update=latest_source_update,
        )

        self._audit.append(
            action="source.dataset.ingest",
            actor=actor,
            target_type="source_dataset",
            target_id=command.dataset_key,
            after_version=run.received,
            correlation_id=correlation_id,
            references=[command.source_system_id, run.ingestion_run_id],
            metadata={
                "received": run.received,
                "accepted": run.accepted,
                "unchanged": run.unchanged,
                "quarantined": run.quarantined,
                "unresolved": run.unresolved,
                "staged": counters["staged"],
                "registered": registered,
            },
        )

        return IngestResult(
            ingestion_run_id=run.ingestion_run_id,
            source_system_id=command.source_system_id,
            dataset_key=command.dataset_key,
            registered=registered,
            publishable=publishable,
            received=run.received,
            accepted=run.accepted,
            unchanged=run.unchanged,
            quarantined=run.quarantined,
            unresolved=run.unresolved,
            staged=counters["staged"],
            snapshot_ids=[item for item in snapshot_ids if item],
            field_errors=all_errors,
            records=outcomes,
            issue_ids=issue_ids,
            received_at=received_at,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------ private

    def _ingest_record(
        self,
        *,
        run: source.IngestionRun,
        contract: governance.SourceContract | None,
        command: IngestCommand,
        record: Any,
        received_at: datetime,
        correlation_id: str,
        registered: bool,
        publishable: bool,
        accepted_ids: set[str],
    ) -> tuple[RecordOutcomeView, list[FieldErrorView], str | None]:
        """Ingest one source record and report its outcome."""
        payload = {
            key: value
            for key, value in dict(record.payload or {}).items()
            if key != CONTROL_FIELD_NAME
        }
        hash_value = payload_hash(payload)
        _require_aware(record.source_updated_at, "source_updated_at")
        _require_aware(record.effective_from, "effective_from")
        _require_aware(record.effective_to, "effective_to")

        validator = PayloadValidator(
            business_key_fields=tuple(contract.business_key_fields or ())
            if contract is not None
            else (),
            required_fields=dict(contract.required_fields or {})
            if contract is not None
            else {},
            allowed_values=dict(contract.allowed_values or {})
            if contract is not None
            else {},
            rules=intake_rules_for(command.dataset_key),
            reference_exists=lambda dataset_key, record_id: self._reference_exists(
                command.source_system_id, dataset_key, record_id, accepted_ids
            ),
        )
        errors = list(validator.validate(payload))
        errors.extend(validator.validate_source_version(record.source_record_version))

        existing = self.snapshot_by_identity(
            command.source_system_id,
            command.dataset_key,
            record.source_record_id,
            record.source_record_version,
            hash_value,
        )
        if existing is not None:
            status = "unchanged" if existing.record_status == "accepted" else existing.record_status
            if existing.record_status == "accepted":
                accepted_ids.add(f"{command.dataset_key}:{record.source_record_id}")
            return (
                RecordOutcomeView(
                    source_record_id=record.source_record_id,
                    source_record_version=record.source_record_version,
                    status=status,
                    source_snapshot_id=existing.source_snapshot_id,
                    payload_hash=hash_value,
                    field_errors=[FieldErrorView(**error.to_dict()) for error in errors],
                ),
                [FieldErrorView(**error.to_dict()) for error in errors],
                None,
            )

        if errors:
            snapshot = self._write_snapshot(
                run=run,
                command=command,
                record=record,
                payload=payload,
                hash_value=hash_value,
                received_at=received_at,
                correlation_id=correlation_id,
                record_status="quarantined",
            )
            for error in errors:
                self._session.add(
                    source.QuarantineError(
                        id=new_id("err"),
                        source_snapshot_id=snapshot.source_snapshot_id,
                        field_path=error.field_path,
                        error_code=error.error_code,
                        message=error.message,
                        responsible_queue_id=(
                            contract.steward_queue_id if contract is not None else None
                        ),
                        status="open",
                    )
                )
            return (
                RecordOutcomeView(
                    source_record_id=record.source_record_id,
                    source_record_version=record.source_record_version,
                    status="quarantined",
                    source_snapshot_id=snapshot.source_snapshot_id,
                    payload_hash=hash_value,
                    field_errors=[FieldErrorView(**error.to_dict()) for error in errors],
                ),
                [FieldErrorView(**error.to_dict()) for error in errors],
                None,
            )

        if not registered or not publishable:
            snapshot = self._write_snapshot(
                run=run,
                command=command,
                record=record,
                payload=payload,
                hash_value=hash_value,
                received_at=received_at,
                correlation_id=correlation_id,
                record_status="staged",
            )
            issue_id = self._raise_unregistered_dataset_issue(command)
            return (
                RecordOutcomeView(
                    source_record_id=record.source_record_id,
                    source_record_version=record.source_record_version,
                    status="staged",
                    source_snapshot_id=snapshot.source_snapshot_id,
                    payload_hash=hash_value,
                ),
                [],
                issue_id,
            )

        current = self.current_accepted_snapshot(
            command.source_system_id, command.dataset_key, record.source_record_id
        )
        issue_id: str | None = None
        status = "accepted"
        if current is not None:
            same_version = (
                record.source_record_version is not None
                and current.source_record_version is not None
                and str(record.source_record_version) == str(current.source_record_version)
            )
            if same_version:
                status = HISTORY_STATUS
                issue_id = self._raise_source_conflict_issue(
                    command, record, contract, current, hash_value
                )
            elif _is_older(
                record.source_record_version,
                record.source_updated_at,
                current.source_record_version,
                current.source_updated_at,
            ):
                status = HISTORY_STATUS
                issue_id = self._raise_late_version_issue(command, record, contract, current)

        snapshot = self._write_snapshot(
            run=run,
            command=command,
            record=record,
            payload=payload,
            hash_value=hash_value,
            received_at=received_at,
            correlation_id=correlation_id,
            record_status=status,
        )
        if status == "accepted":
            accepted_ids.add(f"{command.dataset_key}:{record.source_record_id}")
        return (
            RecordOutcomeView(
                source_record_id=record.source_record_id,
                source_record_version=record.source_record_version,
                status=status,
                source_snapshot_id=snapshot.source_snapshot_id,
                payload_hash=hash_value,
                issue_id=issue_id,
            ),
            [],
            issue_id,
        )

    def _reference_exists(
        self,
        source_system_id: str,
        dataset_key: str,
        record_id: str,
        accepted_ids: set[str],
    ) -> bool:
        """Return whether a referenced record is known inside its source system."""
        if f"{dataset_key}:{record_id}" in accepted_ids:
            return True
        return self.reference_exists(source_system_id, dataset_key, record_id)

    def _write_snapshot(
        self,
        *,
        run: source.IngestionRun,
        command: IngestCommand,
        record: Any,
        payload: dict[str, Any],
        hash_value: str,
        received_at: datetime,
        correlation_id: str,
        record_status: str,
    ) -> source.SourceSnapshot:
        """Preserve one raw payload as an immutable snapshot."""
        snapshot = source.SourceSnapshot(
            source_snapshot_id=new_id("snap"),
            ingestion_run_id=run.ingestion_run_id,
            correlation_id=correlation_id,
            source_system_id=command.source_system_id,
            source_dataset_id=command.dataset_key,
            source_record_id=record.source_record_id,
            source_record_version=record.source_record_version,
            source_updated_at=record.source_updated_at,
            effective_from=record.effective_from,
            effective_to=record.effective_to,
            ingested_at=received_at,
            payload_hash=hash_value,
            raw_payload=payload,
            record_status=record_status,
            scenario_id=record.scenario_id or command.scenario_id,
        )
        self._session.add(snapshot)
        self._session.flush()
        return snapshot

    def _record_observations(
        self,
        *,
        run: source.IngestionRun,
        command: IngestCommand,
        counters: dict[str, int],
        received_at: datetime,
        latest_source_update: datetime | None,
    ) -> None:
        """Record the intake denominators as counted observations."""
        values = {
            "records_received": run.received,
            "records_accepted": counters["accepted"],
            "records_unchanged": counters["unchanged"],
            "records_quarantined": counters["quarantined"],
            "records_unresolved": counters["unresolved"],
            "records_staged": counters["staged"],
        }
        for metric in OBSERVATION_METRICS:
            self._session.add(
                source.SourceObservation(
                    id=new_id("obsv"),
                    source_system_id=command.source_system_id,
                    dataset_key=command.dataset_key,
                    ingestion_run_id=run.ingestion_run_id,
                    metric=metric,
                    numerator=values[metric],
                    denominator=run.received,
                    observed_at=self._now,
                    source_updated_at=latest_source_update,
                    received_at=received_at,
                    scenario_id=command.scenario_id,
                )
            )
        self._session.flush()

    # ------------------------------------------------------------------- issues

    def _open_issue(
        self,
        *,
        subject_type: str,
        subject_id: str,
        issue_type: str,
        description: str,
        responsible_queue_id: str | None,
        assigned_actor_id: str | None,
        blocking: bool,
        scenario_id: str | None,
    ) -> str:
        """Create an open issue unless one is already open for the subject."""
        existing = self._session.execute(
            select(change.GovernanceIssue).where(
                change.GovernanceIssue.subject_type == subject_type,
                change.GovernanceIssue.subject_id == subject_id,
                change.GovernanceIssue.issue_type == issue_type,
                change.GovernanceIssue.status == "open",
            )
        ).scalars().first()
        if existing is not None:
            return existing.id
        issue = change.GovernanceIssue(
            id=new_id("issue"),
            subject_type=subject_type,
            subject_id=subject_id,
            issue_type=issue_type,
            description=description,
            responsible_queue_id=responsible_queue_id,
            assigned_actor_id=assigned_actor_id,
            blocking=blocking,
            status="open",
            scenario_id=scenario_id,
        )
        self._session.add(issue)
        self._session.flush()
        return issue.id

    def _raise_unregistered_dataset_issue(self, command: IngestCommand) -> str:
        """Record the governance work an unowned feed needs before publication."""
        issue_id = self._open_issue(
            subject_type="source_dataset",
            subject_id=command.dataset_key,
            issue_type="unregistered_dataset",
            description=(
                f"the feed {command.source_system_id}/{command.dataset_key} has no complete "
                "governance registration, so its records are staged and cannot publish "
                "trusted facts"
            ),
            responsible_queue_id=None,
            assigned_actor_id=GOVERNANCE_ROUTING_ACTOR_ID,
            blocking=True,
            scenario_id=command.scenario_id,
        )
        deduplication_key = f"dataset_registration:{command.source_system_id}:{command.dataset_key}"
        task = self._session.execute(
            select(change.ReviewTask).where(
                change.ReviewTask.deduplication_key == deduplication_key
            )
        ).scalars().first()
        if task is None:
            self._session.add(
                change.ReviewTask(
                    id=new_id("task"),
                    change_case_id=None,
                    assignee_actor_id=GOVERNANCE_ROUTING_ACTOR_ID,
                    task_type="dataset_registration",
                    target_type="source_dataset",
                    target_id=command.dataset_key,
                    deduplication_key=deduplication_key,
                    status="open",
                    due_at=None,
                    scenario_id=command.scenario_id,
                )
            )
            self._session.flush()
        return issue_id

    def _raise_late_version_issue(
        self,
        command: IngestCommand,
        record: Any,
        contract: governance.SourceContract | None,
        current: source.SourceSnapshot,
    ) -> str:
        """Record a late arrival that is preserved as history only."""
        subject_id = f"{command.source_system_id}:{command.dataset_key}:{record.source_record_id}"
        return self._open_issue(
            subject_type="source_record",
            subject_id=subject_id,
            issue_type="late_source_version",
            description=(
                f"version {record.source_record_version!r} arrived after version "
                f"{current.source_record_version!r} was accepted; the late version is "
                "preserved as history and does not replace the accepted value"
            ),
            responsible_queue_id=contract.steward_queue_id if contract is not None else None,
            assigned_actor_id=self._steward_actor_id(contract),
            blocking=False,
            scenario_id=record.scenario_id or command.scenario_id,
        )

    def _raise_source_conflict_issue(
        self,
        command: IngestCommand,
        record: Any,
        contract: governance.SourceContract | None,
        current: source.SourceSnapshot,
        hash_value: str,
    ) -> str:
        """Record two different payloads claiming the same source version."""
        subject_id = f"{command.source_system_id}:{command.dataset_key}:{record.source_record_id}"
        return self._open_issue(
            subject_type="source_record",
            subject_id=subject_id,
            issue_type="source_version_payload_conflict",
            description=(
                f"version {record.source_record_version!r} was delivered with a different "
                "payload than the accepted version; the accepted value is unchanged until "
                "a steward resolves the contradiction"
            ),
            responsible_queue_id=contract.steward_queue_id if contract is not None else None,
            assigned_actor_id=self._steward_actor_id(contract),
            blocking=True,
            scenario_id=record.scenario_id or command.scenario_id,
        )

    def _steward_actor_id(self, contract: governance.SourceContract | None) -> str | None:
        """Return the steward who owns a dataset."""
        if contract is None or not contract.steward_queue_id:
            return None
        queue = self._session.execute(
            select(governance.StewardQueue).where(
                governance.StewardQueue.queue_id == contract.steward_queue_id
            )
        ).scalar_one_or_none()
        return queue.primary_actor_id if queue is not None else None


__all__ = ["GOVERNANCE_ROUTING_ACTOR_ID", "HISTORY_STATUS", "OBSERVATION_METRICS", "IngestionService"]
