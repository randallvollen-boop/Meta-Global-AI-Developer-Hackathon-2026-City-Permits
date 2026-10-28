"""Governed what-if scenarios and immutable runs.

Every read and every write of a scenario, a run, a briefing and a download
goes through :class:`PolicyService`, which checks the dedicated policy grant
first, whoever is asking and however the record was addressed.  A write also
needs a mandatory expected version (a missing version is refused as firmly as
a stale one) and appends an audit record that names the record and its
versions and carries no free text.  The CSRF check belongs to the route; this
service is what the routes and the tests both call.

Saving a scenario never changes a published rule, a fee, a permit type or an
application.  A run re-scores frozen inputs in memory and stores a snapshot
beside the live tables.
"""
# REQUIRES: PER-02, PER-04, SEC-01, SEC-03
# Policy scenarios and runs: grant, mandatory version, audit and immutability.

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import ConflictError, NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.persistence.models import policy as models
from acme_city.policy import runs
from acme_city.policy.baseline import freeze_baseline
from acme_city.policy.changes import ChangeError
from acme_city.policy.config import PolicyConfig
from acme_city.policy.loader import current_applications_population, decided_range_population
from acme_city.policy.population import (
    KIND_CURRENT,
    KIND_DECIDED_RANGE,
    KIND_SYNTHETIC_YEAR,
    Population,
)
from acme_city.policy.suggestions import suggestion, suggestion_changes

PERMISSION_MANAGE = "policy.scenario.manage"
PERMISSION_EXECUTE = "policy.run.execute"
PERMISSION_RUN_VIEW = "policy.run.view"
PERMISSION_BRIEF_VIEW = "policy.brief.view"

ACTION_CREATE = "policy.scenario.create"
ACTION_EDIT = "policy.scenario.edit"
ACTION_DELETE = "policy.scenario.delete"
ACTION_RUN = "policy.run.execute"
ACTION_DOWNLOAD = "policy.brief.download"

OPERATIONS = ("rename", "add_change", "remove_change")

MAX_NAME_LENGTH = 200
MAX_CHANGES = 25


def _require_version(expected_version: int | None) -> int:
    if expected_version is None:
        raise ValidationError("an expected version is required for this action")
    return expected_version


class PolicyService:
    """Scenarios, revisions and runs, under the dedicated policy grants."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    # ------------------------------------------------------------------ grants

    def _authorize(self, actor: ActorContext, *permissions: str) -> None:
        for permission in permissions:
            self._permissions.authorize(actor, permission, ResourceContext(domain_id=None))

    def can(self, actor: ActorContext, permission: str) -> bool:
        return self._permissions.allows(actor, permission, ResourceContext(domain_id=None))

    # ------------------------------------------------------------------- reads

    def list_scenarios(self, actor: ActorContext) -> list[models.PolicyScenario]:
        """Return the scenarios that are not deleted, newest first."""
        self._authorize(actor, PERMISSION_MANAGE)
        return list(
            self._session.execute(
                select(models.PolicyScenario)
                .where(models.PolicyScenario.deleted_at.is_(None))
                .order_by(models.PolicyScenario.created_at.desc(), models.PolicyScenario.id)
            ).scalars()
        )

    def scenario_for(
        self, actor: ActorContext, scenario_id: str, *, include_deleted: bool = False
    ) -> models.PolicyScenario:
        self._authorize(actor, PERMISSION_MANAGE)
        row = self._session.get(models.PolicyScenario, scenario_id)
        if row is None:
            raise NotFoundError("no what-if has that identifier")
        if row.deleted_at is not None and not include_deleted:
            raise NotFoundError("that what-if was deleted; the runs made from it are kept")
        return row

    def revision(
        self, actor: ActorContext, scenario: models.PolicyScenario, number: int | None = None
    ) -> models.PolicyScenarioRevision:
        self._authorize(actor, PERMISSION_MANAGE)
        wanted = number or scenario.current_revision
        row = self._session.execute(
            select(models.PolicyScenarioRevision).where(
                models.PolicyScenarioRevision.scenario_id == scenario.id,
                models.PolicyScenarioRevision.revision_number == wanted,
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("that revision does not exist")
        return row

    def revisions(
        self, actor: ActorContext, scenario: models.PolicyScenario
    ) -> list[models.PolicyScenarioRevision]:
        self._authorize(actor, PERMISSION_MANAGE)
        return list(
            self._session.execute(
                select(models.PolicyScenarioRevision)
                .where(models.PolicyScenarioRevision.scenario_id == scenario.id)
                .order_by(models.PolicyScenarioRevision.revision_number.desc())
            ).scalars()
        )

    def runs_of(self, actor: ActorContext, scenario_id: str) -> list[models.PolicyRun]:
        self._authorize(actor, PERMISSION_RUN_VIEW)
        return list(
            self._session.execute(
                select(models.PolicyRun)
                .where(models.PolicyRun.scenario_id == scenario_id)
                .order_by(models.PolicyRun.created_at.desc(), models.PolicyRun.id)
            ).scalars()
        )

    def recent_runs(self, actor: ActorContext, limit: int = 20) -> list[models.PolicyRun]:
        """Return the newest runs, including those of deleted scenarios."""
        self._authorize(actor, PERMISSION_RUN_VIEW)
        return list(
            self._session.execute(
                select(models.PolicyRun)
                .order_by(models.PolicyRun.created_at.desc(), models.PolicyRun.id)
                .limit(limit)
            ).scalars()
        )

    def run_for(self, actor: ActorContext, run_id: str) -> models.PolicyRun:
        """Return a run for reading (needs ``policy.run.view``)."""
        self._authorize(actor, PERMISSION_RUN_VIEW)
        row = self._session.get(models.PolicyRun, run_id)
        if row is None:
            raise NotFoundError("no run has that identifier")
        return row

    def run_for_briefing(self, actor: ActorContext, run_id: str) -> models.PolicyRun:
        """Return a run for its briefing (needs ``policy.brief.view``)."""
        self._authorize(actor, PERMISSION_BRIEF_VIEW)
        row = self._session.get(models.PolicyRun, run_id)
        if row is None:
            raise NotFoundError("no run has that identifier")
        return row

    def scenario_state(self, scenario_id: str) -> tuple[bool, str] | None:
        """Return ``(deleted, name)`` for display next to a run, or ``None``."""
        row = self._session.get(models.PolicyScenario, scenario_id)
        return None if row is None else (row.deleted_at is not None, row.name)

    def baseline(self) -> PolicyConfig:
        """Freeze the published configuration now (reads only)."""
        return freeze_baseline(self._session, self._now)

    # ------------------------------------------------------------------ writes

    def _clean_name(self, name: str) -> str:
        clean = str(name or "").strip()
        if not clean:
            raise ValidationError("a what-if needs a name")
        if len(clean) > MAX_NAME_LENGTH:
            raise ValidationError(f"the name is longer than {MAX_NAME_LENGTH} characters")
        return clean

    def _normalise(self, changes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        if len(changes) > MAX_CHANGES:
            raise ValidationError(f"a what-if holds at most {MAX_CHANGES} changes")
        try:
            return [runs.normalise_change(item) for item in changes]
        except ChangeError as error:
            raise ValidationError(error.message) from error

    def _add_revision(
        self,
        scenario: models.PolicyScenario,
        actor: ActorContext,
        *,
        number: int,
        name: str,
        changes: list[dict[str, Any]],
        starting: Mapping[str, Any] | None,
        operation: str,
    ) -> models.PolicyScenarioRevision:
        row = models.PolicyScenarioRevision(
            id=new_id("polrev"),
            created_at=self._now,
            scenario_id=scenario.id,
            revision_number=number,
            name=name,
            changes=changes,
            starting_population=None if starting is None else dict(starting),
            operation=operation,
            content_hash=runs.revision_content_hash(name, changes, starting),
            created_by_actor_id=actor.actor_id,
        )
        self._session.add(row)
        return row

    def create_scenario(
        self,
        actor: ActorContext,
        *,
        name: str,
        changes: Sequence[Mapping[str, Any]] = (),
        starting_population: Mapping[str, Any] | None = None,
        suggestion_key: str | None = None,
        expected_version: int | None = None,
        source_proposal_id: str | None = None,
    ) -> models.PolicyScenario:
        """Save a new what-if as revision 1.

        A new record starts at version 0, so the expected version of a create
        is 0 (the same rule the help conversations follow).  A what-if that
        Muse proposed is saved here too, only after the Administrator pressed
        save; ``source_proposal_id`` names the recorded proposal in the audit.
        """
        self._authorize(actor, PERMISSION_MANAGE)
        if _require_version(expected_version) != 0:
            raise ConflictError("a new what-if starts at version 0; read the screen again and retry")
        if suggestion_key:
            chosen = suggestion(suggestion_key)
            if chosen is None:
                raise ValidationError("that suggested what-if does not exist")
            if not name.strip():
                name = chosen.title
            if not changes:
                changes = suggestion_changes(suggestion_key, self.baseline())
        clean = self._clean_name(name)
        stored = self._normalise(changes)
        starting = {k: v for k, v in (starting_population or {}).items() if v} or None
        scenario = models.PolicyScenario(
            id=new_id("polscen"),
            correlation_id=new_id("corr"),
            created_at=self._now,
            name=clean,
            created_by_actor_id=actor.actor_id,
            current_revision=1,
            suggestion_key=suggestion_key or None,
            version=1,
        )
        self._session.add(scenario)
        self._session.flush()
        revision = self._add_revision(
            scenario, actor, number=1, name=clean, changes=stored, starting=starting,
            operation="create",
        )
        self._session.flush()
        self._audit.append(
            action=ACTION_CREATE,
            actor=actor,
            target_type="policy_scenario",
            target_id=scenario.id,
            before_version=0,
            after_version=scenario.version,
            reason="the City Administrator saved a new what-if",
            references=[revision.id],
            correlation_id=scenario.correlation_id,
            metadata={
                "scenario_id": scenario.id,
                "revision": 1,
                "change_count": len(stored),
                "content_hash": revision.content_hash,
                **({"source_proposal_id": source_proposal_id} if source_proposal_id else {}),
            },
        )
        self._session.flush()
        return scenario

    def edit_scenario(
        self,
        actor: ActorContext,
        scenario_id: str,
        *,
        operation: str,
        expected_version: int | None,
        name: str | None = None,
        change: Mapping[str, Any] | None = None,
        change_index: int | None = None,
    ) -> models.PolicyScenario:
        """Save a new revision: rename, add a change or remove a change."""
        scenario = self.scenario_for(actor, scenario_id)
        expected = _require_version(expected_version)
        if expected != scenario.version:
            raise ConflictError(
                "the what-if changed since it was read; read it again and retry",
                current_version=scenario.version,
            )
        if operation not in OPERATIONS:
            raise ValidationError("the edit is not one of rename, add_change or remove_change")
        current = self.revision(actor, scenario)
        new_name = current.name
        changes = [dict(item) for item in current.changes]
        if operation == "rename":
            new_name = self._clean_name(name or "")
        elif operation == "add_change":
            if change is None:
                raise ValidationError("a change is required")
            changes.extend(self._normalise([change]))
            changes = self._normalise(changes)
        else:
            if change_index is None or not 0 <= change_index < len(changes):
                raise ValidationError("that change is not in the what-if")
            del changes[change_index]
        number = scenario.current_revision + 1
        revision = self._add_revision(
            scenario, actor, number=number, name=new_name, changes=changes,
            starting=current.starting_population, operation=operation,
        )
        before = scenario.version
        scenario.name = new_name
        scenario.current_revision = number
        scenario.version = before + 1
        self._session.flush()
        self._audit.append(
            action=ACTION_EDIT,
            actor=actor,
            target_type="policy_scenario",
            target_id=scenario.id,
            before_version=before,
            after_version=scenario.version,
            reason="the City Administrator saved a revision of a what-if",
            references=[revision.id],
            correlation_id=scenario.correlation_id,
            metadata={
                "scenario_id": scenario.id,
                "revision": number,
                "operation": operation,
                "change_count": len(changes),
                "content_hash": revision.content_hash,
            },
        )
        self._session.flush()
        return scenario

    def delete_scenario(
        self, actor: ActorContext, scenario_id: str, *, expected_version: int | None
    ) -> models.PolicyScenario:
        """Soft-delete a what-if.  Its revisions and its runs are kept."""
        scenario = self.scenario_for(actor, scenario_id)
        expected = _require_version(expected_version)
        if expected != scenario.version:
            raise ConflictError(
                "the what-if changed since it was read; read it again and retry",
                current_version=scenario.version,
            )
        before = scenario.version
        scenario.deleted_at = self._now
        scenario.deleted_by_actor_id = actor.actor_id
        scenario.version = before + 1
        self._session.flush()
        self._audit.append(
            action=ACTION_DELETE,
            actor=actor,
            target_type="policy_scenario",
            target_id=scenario.id,
            before_version=before,
            after_version=scenario.version,
            reason="the City Administrator deleted a what-if (a soft delete; its runs are kept)",
            correlation_id=scenario.correlation_id,
            metadata={"scenario_id": scenario.id, "soft_delete": True},
        )
        self._session.flush()
        return scenario

    # -------------------------------------------------------------------- runs

    def _population(self, spec: runs.PopulationSpec) -> Population:
        if spec.kind == KIND_SYNTHETIC_YEAR:
            return runs.build_synthetic(spec)
        if spec.kind == KIND_CURRENT:
            stored = current_applications_population(self._session)
        elif spec.kind == KIND_DECIDED_RANGE:
            stored = decided_range_population(
                self._session,
                datetime.fromisoformat(spec.range_start).replace(tzinfo=self._now.tzinfo),
                datetime.fromisoformat(spec.range_end).replace(tzinfo=self._now.tzinfo),
            )
        else:  # pragma: no cover - the spec refuses other kinds
            raise ValidationError("unknown population kind")
        return runs.label_for(runs.narrow_stored(stored, spec), spec)

    def run_scenario(
        self,
        actor: ActorContext,
        scenario_id: str,
        *,
        expected_version: int | None,
        spec: runs.PopulationSpec | Mapping[str, Any],
    ) -> models.PolicyRun:
        """Run the latest revision over a population and keep the snapshot."""
        self._authorize(actor, PERMISSION_EXECUTE)
        scenario = self.scenario_for(actor, scenario_id)
        expected = _require_version(expected_version)
        if expected != scenario.version:
            raise ConflictError(
                "the what-if changed since it was read; read it again and retry",
                current_version=scenario.version,
            )
        try:
            population_spec = (
                spec if isinstance(spec, runs.PopulationSpec) else runs.PopulationSpec.from_mapping(spec)
            )
        except runs.SpecError as error:
            raise ValidationError(str(error)) from error
        revision = self.revision(actor, scenario)
        if not revision.changes:
            raise ValidationError("add at least one change before running the what-if")
        baseline = self.baseline()
        try:
            population = self._population(population_spec)
            executed = runs.execute(
                scenario_name=revision.name,
                changes=revision.changes,
                baseline=baseline,
                spec=population_spec,
                population=population,
            )
        except runs.UnsupportedScenario as error:
            raise ValidationError(str(error), code="unsupported_change") from error
        except ValueError as error:
            raise ValidationError(str(error)) from error
        if executed.population.size == 0:
            raise ValidationError("the population is empty; widen the choice and try again")
        run = models.PolicyRun(
            id=new_id("polrun"),
            correlation_id=scenario.correlation_id,
            created_at=self._now,
            scenario_id=scenario.id,
            scenario_revision_id=revision.id,
            scenario_revision_number=revision.revision_number,
            scenario_name=revision.name,
            created_by_actor_id=actor.actor_id,
            analysis_at=baseline.analysis_at,
            engine_version=executed.impact.engine_version,
            generator_version=executed.generator_version,
            population_kind=executed.population.definition.kind,
            population_label=executed.population.definition.display_label,
            population_synthetic=executed.population.definition.synthetic,
            population_size=executed.population.size,
            population_spec=population_spec.canonical(),
            population_definition=executed.population.definition.canonical(),
            baseline_config=baseline.canonical(),
            proposed_config=executed.scenario_result.config.canonical(),  # type: ignore[union-attr]
            case_inputs=executed.case_inputs,
            result=executed.result,
            baseline_hash=executed.impact.baseline_hash,
            proposed_hash=executed.impact.scenario_config_hash,
            population_hash=executed.impact.population_hash,
            result_hash=executed.impact.result_hash,
            content_hash=executed.content_hash,
        )
        self._session.add(run)
        self._session.flush()
        self._audit.append(
            action=ACTION_RUN,
            actor=actor,
            target_type="policy_run",
            target_id=run.id,
            before_version=scenario.version,
            after_version=scenario.version,
            reason="the City Administrator ran a what-if over a population",
            references=[scenario.id, revision.id],
            correlation_id=scenario.correlation_id,
            metadata={
                "run_id": run.id,
                "scenario_id": scenario.id,
                "revision": revision.revision_number,
                "population_kind": run.population_kind,
                "population_size": run.population_size,
                "synthetic": run.population_synthetic,
                "content_hash": run.content_hash,
            },
        )
        self._session.flush()
        return run

    def verify_run(self, actor: ActorContext, run: models.PolicyRun) -> bool:
        """Return whether a stored run still hashes to its content hash."""
        self._authorize(actor, PERMISSION_RUN_VIEW)
        revision = self._session.get(models.PolicyScenarioRevision, run.scenario_revision_id)
        if revision is None:
            return False
        recomputed = runs.content_hash_from_snapshot(
            changes=revision.changes,
            scenario_name=run.scenario_name,
            baseline_config=run.baseline_config,
            proposed_config=run.proposed_config,
            case_inputs=run.case_inputs,
            population_definition=run.population_definition,
            analysis_at=run.analysis_at.isoformat(),
            engine_version=run.engine_version,
            generator_version=run.generator_version,
        )
        return recomputed == run.content_hash

    def record_download(self, actor: ActorContext, run: models.PolicyRun, fmt: str) -> None:
        """Audit a briefing download (the file itself is built by the caller)."""
        self._audit.append(
            action=ACTION_DOWNLOAD,
            actor=actor,
            target_type="policy_run",
            target_id=run.id,
            reason="the City Administrator downloaded a briefing",
            references=[run.scenario_id],
            correlation_id=run.correlation_id,
            metadata={"run_id": run.id, "format": fmt, "content_hash": run.content_hash},
        )


__all__ = [
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_DOWNLOAD",
    "ACTION_EDIT",
    "ACTION_RUN",
    "MAX_CHANGES",
    "OPERATIONS",
    "PERMISSION_BRIEF_VIEW",
    "PERMISSION_EXECUTE",
    "PERMISSION_MANAGE",
    "PERMISSION_RUN_VIEW",
    "PolicyService",
]
