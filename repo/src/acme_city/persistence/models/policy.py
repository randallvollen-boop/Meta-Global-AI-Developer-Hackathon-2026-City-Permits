"""Policy what-if scenarios, their revisions and their immutable runs.

* A **scenario** is a named what-if.  Every edit saves a new **revision**; the
  scenario row only points at the latest one.  Deleting a scenario is a soft
  delete: the row keeps its revisions and its runs.
* A **run** is an immutable snapshot of one evaluation.  It holds the scenario
  revision, the complete baseline and proposed configuration, the ordered case
  inputs, the population definition, ``analysis_at``, the engine and generator
  versions and the result.  ``content_hash`` is a canonical hash of that
  content and nothing else, so it never depends on an id or a timestamp.

Nothing here touches a published rule, a fee, a permit type or an
application: a what-if is stored beside the live tables, never in them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import (
    Base,
    CorrelationMixin,
    CreatedAtMixin,
    IdMixin,
    VersionMixin,
)
from acme_city.persistence.types import UTCDateTime


class PolicyScenario(IdMixin, VersionMixin, CorrelationMixin, CreatedAtMixin, Base):
    """A saved what-if.  The latest revision holds its content."""

    __tablename__ = "policy_scenarios"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The number of the latest revision.
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The suggested scenario this one started from, when it did.
    suggestion_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: A soft delete: set when the scenario is deleted, never cleared by a
    #: write path of this release.  Runs and revisions are kept.
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    deleted_by_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PolicyScenarioRevision(IdMixin, CreatedAtMixin, Base):
    """One saved revision of a scenario (append-only)."""

    __tablename__ = "policy_scenario_revisions"
    __table_args__ = (
        UniqueConstraint("scenario_id", "revision_number", name="scenario_revision"),
    )

    scenario_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("policy_scenarios.id"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: The ordered change records, as plain mappings (see ``policy.changes``).
    changes: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    #: The starting population (type, district, category) the scenario was
    #: started from, when it was started from the City view.
    starting_population: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: What this revision did: ``create``, ``rename``, ``add_change`` or
    #: ``remove_change``.
    operation: Mapped[str] = mapped_column(String(32), nullable=False, default="create")
    #: Canonical hash of the name, the changes and the starting population.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor_id: Mapped[str] = mapped_column(String(64), nullable=False)


class PolicyRun(IdMixin, CorrelationMixin, CreatedAtMixin, Base):
    """An immutable evaluation snapshot.  There is no update path."""

    __tablename__ = "policy_runs"

    scenario_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("policy_scenarios.id"), nullable=False, index=True
    )
    scenario_revision_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("policy_scenario_revisions.id"), nullable=False
    )
    scenario_revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The scenario name as it was when the run was made.
    scenario_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generator_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    population_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    population_label: Mapped[str] = mapped_column(String(200), nullable=False)
    population_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    population_size: Mapped[int] = mapped_column(Integer, nullable=False)
    #: How the population was asked for (kind, seed, count, range, narrowing).
    population_spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    population_definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    #: The complete frozen baseline and proposed configurations.
    baseline_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    proposed_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    #: The ordered case inputs, as canonical mappings.
    case_inputs: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    #: The measures and the changed cases (see ``policy.runs``).
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    baseline_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    population_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Canonical hash of the content above, without ids and timestamps.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ImmutableRunError(RuntimeError):
    """Raised when something tries to change or delete a stored run."""


class PolicyDraftConversion(IdMixin, VersionMixin, CorrelationMixin, CreatedAtMixin, Base):
    """The one conversion of a run into draft rule and fee versions.

    A run converts at most once (``run_id`` is unique), so a repeated press
    finds this row instead of making a second set of drafts.  The row names the
    drafts and the content hash of the run it was made from; it never holds the
    drafts' content, which lives in the rule and fee version rows.
    """

    __tablename__ = "policy_draft_conversions"

    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("policy_runs.id"), nullable=False, unique=True
    )
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The run's content hash when it was converted (the version the draft is bound to).
    run_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The Administrator who authored the drafts.
    converted_by_actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Ordered mappings ``{"kind": "rule"|"fee", "id", "label", "change_index"}``.
    drafts: Mapped[list[Any]] = mapped_column(JSON, nullable=False)


@event.listens_for(PolicyRun, "before_update")
def _refuse_update(mapper: Any, connection: Any, target: PolicyRun) -> None:
    raise ImmutableRunError("a policy run is immutable; make a new run instead")


@event.listens_for(PolicyRun, "before_delete")
def _refuse_delete(mapper: Any, connection: Any, target: PolicyRun) -> None:
    raise ImmutableRunError("a policy run is kept; it cannot be deleted")


@event.listens_for(PolicyScenarioRevision, "before_update")
def _refuse_revision_update(mapper: Any, connection: Any, target: Any) -> None:
    raise ImmutableRunError("a scenario revision is append-only")


__all__ = [
    "ImmutableRunError",
    "PolicyDraftConversion",
    "PolicyRun",
    "PolicyScenario",
    "PolicyScenarioRevision",
]
