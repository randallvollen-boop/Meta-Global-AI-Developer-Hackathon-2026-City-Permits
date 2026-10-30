"""Model run traces.

Every run records its mode, provider, model, prompt and schema versions,
inputs, output, validation result, usage and failures.  A credential is never
stored here.  Evaluation truth is never part of a run input.

A run records the engine that produced it.  ``live``, ``replay`` and
``cached`` are the provider paths and keep their labels; ``builtin`` is the
deterministic logic of the City, which sends no provider call and therefore
never claims the label of a replay.

The provider response that produced a run has no column of its own: its
identifier, its status and its refusal are recorded inside the validation
result under :data:`PROVIDER_RESPONSE_KEY`, and :attr:`ModelRun.
provider_response_id` reads them back.  The recording is a correction for the
bounded Muse runs: a run has to be able to name the exact provider response
it belongs to without a second write path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import Base, CorrelationMixin, CreatedAtMixin, IdMixin, VersionMixin
from acme_city.persistence.types import UTCDateTime

#: The key of the validation result that holds the provider response record.
PROVIDER_RESPONSE_KEY: Final = "provider"

#: The recorded outcomes of a model run.
RUN_STATUSES: Final = frozenset({"succeeded", "failed"})

#: The provenance of a run of the deterministic logic of the City.  A run in
#: this mode sent no provider call and replays no earlier run.
BUILTIN_MODE: Final = "builtin"

#: The modes a model run may record.
RUN_MODES: Final = ("live", "replay", "cached", BUILTIN_MODE)


class ModelRun(IdMixin, VersionMixin, CorrelationMixin, CreatedAtMixin, Base):
    """One model execution: live, replay, cached or the built in logic."""

    __tablename__ = "model_runs"

    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="live")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    input_refs: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fixture_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replay_of_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    __table_args__ = (
        CheckConstraint(
            "mode IN ('live', 'replay', 'cached', 'builtin')", name="mode_allowed"
        ),
    )

    @property
    def provider_response_id(self) -> str | None:
        """Return the identifier of the provider response this run belongs to.

        The identifier is recorded inside the validation result, because a
        response and its validation belong to the same record.
        """
        validation = self.validation_result or {}
        provider = validation.get(PROVIDER_RESPONSE_KEY)
        if not isinstance(provider, dict):
            return None
        value = provider.get("response_id")
        return str(value) if value else None

    @property
    def status(self) -> str:
        """Return the recorded outcome of the run.

        A run that never reached a validation is a failed run; a run whose
        validation failed is a failed run.  Neither is ever rewritten.
        """
        validation = self.validation_result or {}
        recorded = validation.get("status")
        if isinstance(recorded, str) and recorded in RUN_STATUSES:
            return recorded
        return "failed"


class ModelInput(IdMixin, CreatedAtMixin, Base):
    """A reference to one input of a model run.

    Only references and content hashes are stored, never a credential and never
    an evaluation-truth field.
    """

    __tablename__ = "model_inputs"

    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("model_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    input_type: Mapped[str] = mapped_column(String(48), nullable=False)
    input_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ModelOutput(IdMixin, CreatedAtMixin, Base):
    """The raw output of a model run and its validation outcome."""

    __tablename__ = "model_outputs"

    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("model_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation_errors: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    validation_state: Mapped[str] = mapped_column(String(32), nullable=False, default="unvalidated")


class EvidenceReference(IdMixin, CreatedAtMixin, Base):
    """A stored reference that a piece of evidence is available locally."""

    __tablename__ = "evidence_references"

    run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    evidence_kind: Mapped[str] = mapped_column(String(48), nullable=False, default="document")
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(96), nullable=False)
    path: Mapped[str] = mapped_column(String(240), nullable=False)
    label: Mapped[str | None] = mapped_column(String(240), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fictional_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


__all__ = [
    "BUILTIN_MODE",
    "PROVIDER_RESPONSE_KEY",
    "RUN_MODES",
    "RUN_STATUSES",
    "EvidenceReference",
    "ModelInput",
    "ModelOutput",
    "ModelRun",
]
