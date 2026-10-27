"""The shared behavior of a simulated source adapter.

An adapter is the local stand-in for one source system.  It owns its own
records and their versions, it requires the expected version of the record it
is asked to change, and it answers with one explicit acknowledgement:
``accepted``, ``rejected``, ``timeout`` or ``conflict``.

An adapter never writes a canonical identity, a review decision, a fee or a
permit.  It only says what its own source would say.
"""
# REQUIRES: EDIT-01, CHG-02, CHG-05, CHG-06, ING-02, ING-03
# Writes are authorized, the expected version is required, source versions are
# persisted, and the acknowledgement is explicit about what the source accepted.

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.ids import new_id
from acme_city.fixtures.loader import payload_hash
from acme_city.ingestion.service import IngestionService
from acme_city.ingestion.validation import (
    CONTROL_FIELD_NAME,
    FieldError,
    PayloadValidator,
    intake_rules_for,
)
from acme_city.persistence.models import governance

#: The acknowledgement states a source may return.
ACKNOWLEDGEMENT_STATUSES: frozenset[str] = frozenset(
    {"accepted", "rejected", "timeout", "conflict"}
)

#: The fixture control modes a source may be told to answer with.
CONTROL_MODES: frozenset[str] = frozenset({"accept", "reject", "timeout", "late"})


@dataclass(frozen=True)
class SourceCommand:
    """A requested write to one source record."""

    source_system_id: str
    dataset_key: str
    record_id: str
    operation: str = "update"
    expected_version: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    request_key: str = ""
    actor_id: str | None = None
    change_case_id: str | None = None


@dataclass(frozen=True)
class SourceAcknowledgement:
    """What the source answered about a requested write."""

    source_system_id: str
    dataset_key: str
    record_id: str
    status: str
    source_record_version: str | None = None
    expected_version: str | None = None
    message: str = ""
    payload_hash: str = ""
    source_snapshot_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        """Return whether the source accepted the write."""
        return self.status == "accepted"

    @property
    def late(self) -> bool:
        """Return whether the acknowledgement carries an older version."""
        return bool(self.details.get("late"))

    def to_dict(self) -> dict[str, Any]:
        """Return the stable dictionary form of the acknowledgement."""
        return {
            "source_system_id": self.source_system_id,
            "dataset_key": self.dataset_key,
            "record_id": self.record_id,
            "status": self.status,
            "source_record_version": self.source_record_version,
            "expected_version": self.expected_version,
            "message": self.message,
            "payload_hash": self.payload_hash,
            "source_snapshot_id": self.source_snapshot_id,
            "details": dict(self.details),
        }


def _control(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return the fixture control of a payload and the payload without it.

    The control is a declared test affordance of the simulated source.  It is
    never stored and it never carries a business meaning.
    """
    raw = payload.get(CONTROL_FIELD_NAME)
    if raw is None:
        return "accept", {}
    if isinstance(raw, dict):
        mode = str(raw.get("mode", "accept")).strip().lower()
        details = {key: value for key, value in raw.items() if key != "mode"}
        return (mode if mode in CONTROL_MODES else "accept"), details
    mode = str(raw).strip().lower()
    return (mode if mode in CONTROL_MODES else "accept"), {}


class SourceAdapter(abc.ABC):
    """The local stand-in for one simulated source system."""

    #: The source system this adapter answers for.
    source_system_id: str = ""
    #: The label the demonstration shows.
    label: str = ""
    #: The datasets this source owns.
    dataset_keys: tuple[str, ...] = ()

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)
        self._ingestion = IngestionService(session, now=self._now)

    # ------------------------------------------------------------------ public

    def apply(self, command: SourceCommand, actor: ActorContext) -> SourceAcknowledgement:
        """Apply one requested write and return the source acknowledgement.

        Args:
            command: The requested write, with the expected version of the
                record it changes.
            actor: The acting actor, resolved from the server-held session.

        Returns:
            The acknowledgement.  A rejected, timed-out or conflicting write
            never changes the accepted source value.
        """
        if command.source_system_id != self.source_system_id:
            raise ValueError(
                f"the {self.source_system_id!r} adapter does not answer for "
                f"{command.source_system_id!r}"
            )
        if command.dataset_key not in self.dataset_keys:
            raise ValueError(
                f"the {self.source_system_id!r} source does not own the dataset "
                f"{command.dataset_key!r}"
            )
        contract = self._ingestion.contract_for(command.source_system_id, command.dataset_key)
        self._permissions.authorize(
            actor,
            "source.record.update",
            ResourceContext(
                domain_id=contract.domain_id if contract is not None else None,
                record_type="source_record",
                record_ids=(command.record_id,),
            ),
        )

        payload = {
            key: value for key, value in dict(command.payload or {}).items() if key != CONTROL_FIELD_NAME
        }
        hash_value = payload_hash(payload)
        current = self._ingestion.current_accepted_snapshot(
            command.source_system_id, command.dataset_key, command.record_id
        )
        current_version = current.source_record_version if current is not None else None

        if (command.expected_version or None) != (current_version or None):
            return SourceAcknowledgement(
                source_system_id=command.source_system_id,
                dataset_key=command.dataset_key,
                record_id=command.record_id,
                status="conflict",
                source_record_version=current_version,
                expected_version=command.expected_version,
                message=(
                    f"the record is at version {current_version!r}; the request expected "
                    f"{command.expected_version!r}"
                ),
                payload_hash=hash_value,
                details={"current_version": current_version},
            )

        mode, control_details = _control(command.payload)
        if mode == "reject":
            return SourceAcknowledgement(
                source_system_id=command.source_system_id,
                dataset_key=command.dataset_key,
                record_id=command.record_id,
                status="rejected",
                source_record_version=current_version,
                expected_version=command.expected_version,
                message="the source refused the change and kept its accepted value",
                payload_hash=hash_value,
                details={"reason": "source_refused", **control_details},
            )
        if mode == "timeout":
            return SourceAcknowledgement(
                source_system_id=command.source_system_id,
                dataset_key=command.dataset_key,
                record_id=command.record_id,
                status="timeout",
                source_record_version=current_version,
                expected_version=command.expected_version,
                message="the source did not answer in time; its accepted value is unchanged",
                payload_hash=hash_value,
                details={"reason": "no_response", **control_details},
            )
        if mode == "late":
            late_version = str(control_details.get("version", current_version or ""))
            return SourceAcknowledgement(
                source_system_id=command.source_system_id,
                dataset_key=command.dataset_key,
                record_id=command.record_id,
                status="accepted",
                source_record_version=late_version or None,
                expected_version=command.expected_version,
                message="the source answered with an earlier version than it holds now",
                payload_hash=hash_value,
                details={"late": True, **control_details},
            )

        errors = self._validate(command, payload)
        if errors:
            return SourceAcknowledgement(
                source_system_id=command.source_system_id,
                dataset_key=command.dataset_key,
                record_id=command.record_id,
                status="rejected",
                source_record_version=current_version,
                expected_version=command.expected_version,
                message="the source refused the change because the payload failed validation",
                payload_hash=hash_value,
                details={"field_errors": [error.to_dict() for error in errors]},
            )

        refusal = self.refuse(command, current)
        if refusal is not None:
            return refusal

        new_version = self._next_version(current_version)
        snapshot = self._write_snapshot(
            command=command,
            contract=contract,
            payload=payload,
            hash_value=hash_value,
            version=new_version,
        )
        self._audit.append(
            action=f"source.{command.source_system_id}.record.update",
            actor=actor,
            target_type="source_record",
            target_id=command.record_id,
            before_version=current_version,
            after_version=new_version,
            correlation_id=command.request_key or None,
            references=[command.dataset_key, snapshot.source_snapshot_id],
        )
        return SourceAcknowledgement(
            source_system_id=command.source_system_id,
            dataset_key=command.dataset_key,
            record_id=command.record_id,
            status="accepted",
            source_record_version=new_version,
            expected_version=command.expected_version,
            message="the source accepted the new version",
            payload_hash=hash_value,
            source_snapshot_id=snapshot.source_snapshot_id,
            details={"accepted_version": new_version},
        )

    def refuse(
        self, command: SourceCommand, current: Any
    ) -> SourceAcknowledgement | None:
        """Return a refusal when this source does not accept the change.

        The base source accepts every validated write.  A source with a
        stricter rule overrides this method.
        """
        return None

    # ----------------------------------------------------------------- private

    def _validate(self, command: SourceCommand, payload: dict[str, Any]) -> list[FieldError]:
        """Validate the payload of a requested write."""
        contract = self._ingestion.contract_for(command.source_system_id, command.dataset_key)
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
            reference_exists=lambda dataset_key, record_id: self._ingestion.reference_exists(
                command.source_system_id, dataset_key, record_id
            ),
        )
        errors = list(validator.validate(payload))
        return errors

    def _next_version(self, current_version: str | None) -> str:
        """Return the version that follows the current one."""
        if current_version is None:
            return "1"
        text = str(current_version).strip()
        if text.isdigit():
            return str(int(text) + 1)
        return f"{text}.1"

    def _write_snapshot(
        self,
        *,
        command: SourceCommand,
        contract: governance.SourceContract | None,
        payload: dict[str, Any],
        hash_value: str,
        version: str,
    ) -> Any:
        """Persist the version the source accepted."""
        from acme_city.persistence.models import source

        registered = contract is not None and contract.registration_state == "complete"
        snapshot = source.SourceSnapshot(
            source_snapshot_id=new_id("snap"),
            ingestion_run_id=None,
            correlation_id=command.request_key or new_id("corr"),
            source_system_id=command.source_system_id,
            source_dataset_id=command.dataset_key,
            source_record_id=command.record_id,
            source_record_version=version,
            source_updated_at=self._now,
            effective_from=None,
            effective_to=None,
            ingested_at=self._now,
            payload_hash=hash_value,
            raw_payload=payload,
            record_status="accepted" if registered else "staged",
            scenario_id=None,
        )
        self._session.add(snapshot)
        self._session.flush()
        return snapshot


_ADAPTERS: dict[str, type[SourceAdapter]] = {}


def register_adapter(adapter_class: type[SourceAdapter]) -> type[SourceAdapter]:
    """Register an adapter class for its source system."""
    _ADAPTERS[adapter_class.source_system_id] = adapter_class
    return adapter_class


def available_adapters() -> tuple[str, ...]:
    """Return the source systems this demonstration can answer for."""
    from acme_city.adapters.sources import erp_finance, gis, intake_portal, permitting  # noqa: F401

    return tuple(sorted(_ADAPTERS))


def adapter_for(source_system_id: str, session: Session, *, now: datetime | None = None) -> SourceAdapter:
    """Return the adapter of a source system.

    Raises:
        NotFoundError: when no adapter answers for the source system.
    """
    from acme_city.adapters.sources import erp_finance, gis, intake_portal, permitting  # noqa: F401
    from acme_city.core.errors import NotFoundError

    adapter_class = _ADAPTERS.get(source_system_id)
    if adapter_class is None:
        raise NotFoundError(f"no simulated source answers for {source_system_id!r}")
    return adapter_class(session, now=now)


__all__ = [
    "ACKNOWLEDGEMENT_STATUSES",
    "CONTROL_MODES",
    "SourceAcknowledgement",
    "SourceAdapter",
    "SourceCommand",
    "adapter_for",
    "available_adapters",
    "register_adapter",
]
