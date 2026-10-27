"""The change service.

The service owns the correction work: the request, the review, the approval,
the source command, the impact registration and the publication.  It never
changes a source fact on its own: a factual change reaches the source only
through an authorized source command, and the accepted value changes only when
the source acknowledges it.
"""
# REQUIRES: CHG-01, CHG-02, CHG-03, CHG-04, CHG-05, CHG-06, EDIT-01, EDIT-02,
# EDIT-03, EDIT-04
# The request, the permitted transitions with their permissions, the impact
# preview, the dependency registration and the source command are implemented here.

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.changes.schemas import (
    ChangeCaseView,
    ChangeDependencyView,
    ChangeRequestCommand,
    ChangeTransitionCommand,
    ImpactPreview,
    ImpactPreviewCommand,
    ReviewTaskView,
    SourceCommandView,
)
from acme_city.changes.dispatcher import create_publication
from acme_city.changes.state_machine import (
    permitted_targets,
    transition_rule,
)
from acme_city.core.clock import utc_now
from acme_city.core.errors import (
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from acme_city.core.ids import new_id
from acme_city.core.results import ConflictResult, VersionedResult
from acme_city.fixtures.loader import payload_hash
from acme_city.registry.provenance import affected_dependents, current_accepted_snapshot
from acme_city.persistence.models import change, governance, permit, registry, source

#: The action a caller needs to ask for a correction.
REQUEST_ACTION = "correction.request.submit"

#: The states that a person may not perform; the dispatcher performs them.
DISPATCHER_STATES: frozenset[str] = frozenset(
    {"source_acknowledged", "published", "synchronization_failed"}
)


class ChangeService:
    """Correction work, its transitions and its impact."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    # ------------------------------------------------------------------ request

    def request(
        self, command: ChangeRequestCommand, actor: ActorContext
    ) -> ChangeCaseView:
        """Create the requested correction and route it to the responsible steward."""
        if command.change_kind not in {"factual", "identity"}:
            raise ValidationError("a change is either a factual change or an identity change")
        source_system_id, dataset_key, record_id = self._parse_target(command)
        contract = self._contract(source_system_id, dataset_key)
        if contract is None and command.target_type == "application":
            contract = self._contract("permitting", "applications_and_permits")
        domain_id = command.domain_id or (
            contract.domain_id if contract is not None else None
        )
        self._permissions.authorize(
            actor,
            REQUEST_ACTION,
            ResourceContext(
                domain_id=domain_id,
                record_type=command.target_type,
                record_ids=(command.target_id,),
            ),
        )
        destination = command.destination or (
            contract.correction_route if contract is not None else None
        )
        assignee = command.assignee_actor_id or self._steward_actor_id(contract)
        expected_version = (
            command.expected_version
            if command.expected_version is not None
            else self._numeric_source_version(source_system_id, dataset_key, record_id)
        )
        case = change.ChangeCase(
            id=new_id("case"),
            correlation_id=new_id("corr"),
            target_type=command.target_type,
            target_id=command.target_id,
            change_kind=command.change_kind,
            title=command.title,
            old_value=dict(command.old_value),
            proposed_value=dict(command.proposed_value),
            reason=command.reason,
            evidence=list(command.evidence),
            requester_actor_id=actor.actor_id,
            assignee_actor_id=assignee,
            approver_actor_id=command.approver_actor_id,
            destination=destination,
            expected_version=expected_version,
            due_at=None,
            status="requested",
            scenario_id=command.scenario_id,
        )
        self._session.add(case)
        self._session.flush()
        self._audit.append(
            action="change.case.request",
            actor=actor,
            target_type=command.target_type,
            target_id=command.target_id,
            after_version=case.version,
            reason=command.reason,
            references=[case.id, assignee or "", destination or ""],
            metadata={"change_kind": command.change_kind},
        )
        return self.case_view(case)

    # --------------------------------------------------------------- transition

    def transition(
        self, command: ChangeTransitionCommand, actor: ActorContext
    ) -> VersionedResult[ChangeCaseView] | ConflictResult:
        """Move a change case to the next permitted state."""
        case = self._session.get(change.ChangeCase, command.change_case_id)
        if case is None:
            raise NotFoundError(f"no change case {command.change_case_id!r} exists")
        if command.expected_version is not None and case.version != command.expected_version:
            return ConflictResult(
                code="version_conflict",
                expected_version=command.expected_version,
                current_version=case.version,
                differences=(
                    {
                        "field": "status",
                        "expected": command.expected_version,
                        "current": case.version,
                    },
                ),
            )
        rule = transition_rule(case.status, command.to_status, case.change_kind)
        if rule is None:
            raise ValidationError(
                f"a case in {case.status!r} cannot move to {command.to_status!r}"
            )
        if rule.performed_by_dispatcher:
            raise ValidationError(
                f"the state {command.to_status!r} is reached by the dispatcher, not by a person"
            )
        self._permissions.authorize(
            actor,
            rule.action,
            ResourceContext(
                domain_id=self._case_domain(case),
                record_type="change_case",
                record_ids=(case.id,),
            ),
        )
        if rule.requires_approver:
            approver_id = command.approver_actor_id or actor.actor_id
            if command.approver_actor_id and command.approver_actor_id != actor.actor_id:
                raise PermissionDeniedError(
                    "an approval is recorded by the approver themselves",
                    actor_id=actor.actor_id,
                    action="change.case.approve",
                )
            if rule.prohibits_self_approval and approver_id == case.requester_actor_id:
                raise PermissionDeniedError(
                    "the requester of a change may not approve it",
                    actor_id=approver_id,
                    action="change.case.approve",
                )
            approver = self._session.execute(
                select(governance.Actor).where(
                    governance.Actor.actor_id == approver_id
                )
            ).scalar_one_or_none()
            if approver is None:
                raise ValidationError(f"unknown approver {approver_id!r}")
            if not approver.active:
                raise ValidationError(f"approver {approver_id!r} is not active")
            case.approver_actor_id = approver_id
        if rule.reason_required and not (command.reason or case.reason):
            raise ValidationError("this transition needs a reason")
        if command.assignee_actor_id:
            case.assignee_actor_id = command.assignee_actor_id
        if command.reason:
            case.reason = command.reason
        if command.evidence:
            case.evidence = list(case.evidence or []) + list(command.evidence)

        before_version = case.version
        if command.to_status == "approved":
            self._register_dependencies(case, actor)
        if command.to_status == "sent_to_source":
            self._create_source_command(case, actor)
        if command.to_status == "registry_committed":
            self._commit_registry_link(case, actor)
        case.status = command.to_status
        case.version = before_version + 1
        self._session.flush()
        event = self._audit.append(
            action=f"change.case.{command.to_status}",
            actor=actor,
            target_type="change_case",
            target_id=case.id,
            before_version=before_version,
            after_version=case.version,
            reason=command.reason,
            references=[case.target_id, case.approver_actor_id or ""],
            metadata={"to_status": command.to_status},
        )
        return VersionedResult(
            value=self.case_view(case), version=case.version, audit_event_id=event.id
        )

    # ------------------------------------------------------------------- impact

    def preview_impact(
        self, command: ImpactPreviewCommand, actor: ActorContext
    ) -> ImpactPreview:
        """Show which records a change would affect before it is approved."""
        entity_ids, application_ids = self._impact_targets(command)
        dependents = affected_dependents(
            self._session, entity_ids=entity_ids, application_ids=application_ids
        )
        total = sum(len(items) for items in dependents.values())
        rechecks = [
            f"recheck the evaluation of {application_id}"
            for application_id in dependents["applications"]
        ]
        rechecks.extend(
            f"reconfirm the decision of {decision_id}" for decision_id in dependents["decisions"]
        )
        rechecks.extend(
            f"review the issued permit {permit_id}" for permit_id in dependents["permits"]
        )
        return ImpactPreview(
            target_type=command.target_type,
            target_id=command.target_id,
            change_case_id=command.change_case_id,
            applications=dependents["applications"],
            evaluations=dependents["evaluations"],
            assessments=dependents["assessments"],
            decisions=dependents["decisions"],
            permits=dependents["permits"],
            affected_applications=dependents["applications"],
            rechecks=rechecks,
            total_affected=total,
        )

    # ------------------------------------------------------------------ helpers

    def _parse_target(
        self, command: ChangeRequestCommand
    ) -> tuple[str | None, str | None, str | None]:
        """Return the source system, dataset and record of a target."""
        if command.target_type != "source_record":
            return None, None, None
        parts = command.target_id.split("/")
        if len(parts) != 3 or not all(parts):
            raise ValidationError(
                "a source record target is written as <source_system>/<dataset>/<record id>"
            )
        return parts[0], parts[1], parts[2]

    def _contract(
        self, source_system_id: str | None, dataset_key: str | None
    ) -> governance.SourceContract | None:
        """Return the registered contract of a dataset."""
        if not source_system_id or not dataset_key:
            return None
        return self._session.execute(
            select(governance.SourceContract).where(
                governance.SourceContract.source_system_id == source_system_id,
                governance.SourceContract.dataset_key == dataset_key,
            )
        ).scalar_one_or_none()

    def _domain_for(
        self, source_system_id: str | None, dataset_key: str | None
    ) -> str | None:
        """Return the domain a dataset belongs to."""
        contract = self._contract(source_system_id, dataset_key)
        return contract.domain_id if contract is not None else None

    def _steward_actor_id(
        self, contract: governance.SourceContract | None
    ) -> str | None:
        """Return the steward who owns a dataset."""
        if contract is None or not contract.steward_queue_id:
            return None
        queue = self._session.execute(
            select(governance.StewardQueue).where(
                governance.StewardQueue.queue_id == contract.steward_queue_id
            )
        ).scalar_one_or_none()
        return queue.primary_actor_id if queue is not None else None

    def _case_domain(self, case: change.ChangeCase) -> str | None:
        """Return the domain a change case belongs to."""
        source_system_id, dataset_key, _ = self._parse_target(
            ChangeRequestCommand(
                target_type=case.target_type,
                target_id=case.target_id,
                title=case.title,
                reason=case.reason or "",
            )
        )
        domain_id = self._domain_for(source_system_id, dataset_key)
        if domain_id is not None:
            return domain_id
        if case.target_type == "canonical_entity":
            crosswalk = self._session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.entity_id == case.target_id
                )
            ).scalars().first()
            if crosswalk is not None:
                return self._domain_for(
                    crosswalk.source_system_id, crosswalk.source_dataset_key or ""
                )
        if case.target_type == "application":
            return self._domain_for("permitting", "applications_and_permits")
        return None

    def _current_source_version(
        self, source_system_id: str | None, dataset_key: str | None, record_id: str | None
    ) -> str | None:
        """Return the current accepted version of a source record."""
        if not source_system_id or not dataset_key or not record_id:
            return None
        snapshot = current_accepted_snapshot(
            self._session, source_system_id, dataset_key, record_id
        )
        return snapshot.source_record_version if snapshot is not None else None

    def _numeric_source_version(
        self, source_system_id: str | None, dataset_key: str | None, record_id: str | None
    ) -> int | None:
        """Return the current accepted version of a source record, when it is a number.

        A source that versions its records with a text identifier keeps that
        identifier in its command; the case then carries no numeric version.
        """
        version = self._current_source_version(source_system_id, dataset_key, record_id)
        if version is None:
            return None
        return int(version) if str(version).strip().isdigit() else None

    def _create_source_command(
        self, case: change.ChangeCase, actor: ActorContext
    ) -> change.SourceCommand:
        """Create the command that carries the approved change to its source."""
        source_system_id, dataset_key, record_id = self._parse_target(
            ChangeRequestCommand(
                target_type=case.target_type,
                target_id=case.target_id,
                title=case.title,
                reason=case.reason or "",
            )
        )
        if not source_system_id or not dataset_key or not record_id:
            raise ValidationError("only a source record change can be sent to a source")
        payload = dict(case.proposed_value or {})
        hash_value = payload_hash(payload)
        retry_key = f"cmd:{case.id}:{source_system_id}:{dataset_key}:{hash_value}"
        existing = self._session.execute(
            select(change.SourceCommand).where(change.SourceCommand.retry_key == retry_key)
        ).scalars().first()
        if existing is not None:
            return existing
        expected_source_version = self._current_source_version(
            source_system_id, dataset_key, record_id
        )
        command = change.SourceCommand(
            id=new_id("cmd"),
            change_case_id=case.id,
            source_system_id=source_system_id,
            expected_source_version=expected_source_version,
            operation="update",
            payload=payload,
            payload_hash=hash_value,
            retry_key=retry_key,
            status="pending",
            response=None,
            accepted_source_version=None,
            actor_id=actor.actor_id,
        )
        self._session.add(command)
        self._session.flush()
        return command

    def _commit_registry_link(
        self, case: change.ChangeCase, actor: ActorContext
    ) -> None:
        """Record that the registry holds the approved link of an identity change."""
        case.evidence = list(case.evidence or []) + [
            {
                "field": "registry_commit",
                "method": "registry_crosswalk_decision",
                "detail": (
                    "the approved link was committed by the registry before the change was "
                    "published"
                ),
            }
        ]
        create_publication(self._session, case, now=self._now)

    def _register_dependencies(
        self, case: change.ChangeCase, actor: ActorContext
    ) -> list[str]:
        """Register the dependent records and one review task per dependency."""
        entity_ids, application_ids = self._impact_targets(
            ImpactPreviewCommand(target_type=case.target_type, target_id=case.target_id)
        )
        dependents = affected_dependents(
            self._session, entity_ids=entity_ids, application_ids=application_ids
        )
        task_ids: list[str] = []
        for consumer_type, consumer_ids in dependents.items():
            for consumer_id in consumer_ids:
                event_id = f"{case.id}:{case.version + 1}"
                existing = self._session.execute(
                    select(change.ChangeDependency).where(
                        change.ChangeDependency.change_case_id == case.id,
                        change.ChangeDependency.consumer_type == consumer_type,
                        change.ChangeDependency.consumer_id == consumer_id,
                        change.ChangeDependency.event_id == event_id,
                    )
                ).scalars().first()
                if existing is not None:
                    continue
                deduplication_key = f"{case.id}:{consumer_type}:{consumer_id}:{event_id}"
                task = self._session.execute(
                    select(change.ReviewTask).where(
                        change.ReviewTask.deduplication_key == deduplication_key
                    )
                ).scalars().first()
                if task is None:
                    task = change.ReviewTask(
                        id=new_id("task"),
                        change_case_id=case.id,
                        assignee_actor_id=case.assignee_actor_id or actor.actor_id,
                        task_type=f"{consumer_type}_recheck",
                        target_type=consumer_type,
                        target_id=consumer_id,
                        deduplication_key=deduplication_key,
                        status="open",
                        due_at=None,
                        scenario_id=case.scenario_id,
                    )
                    self._session.add(task)
                    self._session.flush()
                dependency = change.ChangeDependency(
                    id=new_id("dep"),
                    change_case_id=case.id,
                    consumer_type=consumer_type,
                    consumer_id=consumer_id,
                    event_id=event_id,
                    invalidation_state="affected",
                    task_id=task.id,
                    scenario_id=case.scenario_id,
                )
                self._session.add(dependency)
                task_ids.append(task.id)
        self._session.flush()
        return task_ids

    def _impact_targets(
        self, command: ImpactPreviewCommand
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Return the entities and applications a target depends on.

        A source record reaches the parties through the official place it
        names: an address reaches the parties whose application site uses it,
        and a parcel reaches them through its addresses.
        """
        entity_ids: list[str] = []
        application_ids: list[str] = []
        if command.target_type == "canonical_entity":
            entity_ids.append(command.target_id)
        elif command.target_type == "source_record":
            parts = command.target_id.split("/")
            if len(parts) == 3:
                source_system_id, dataset_key, record_id = parts
                crosswalk = self._session.execute(
                    select(registry.Crosswalk).where(
                        registry.Crosswalk.source_system_id == source_system_id,
                        registry.Crosswalk.source_record_id == record_id,
                        registry.Crosswalk.link_status == "approved",
                    )
                ).scalars().first()
                if crosswalk is not None:
                    entity_ids.append(crosswalk.entity_id)
                entity_ids.extend(self._place_dependents(source_system_id, dataset_key, record_id))
        return tuple(dict.fromkeys(entity_ids)), tuple(application_ids)

    def _place_dependents(
        self, source_system_id: str, dataset_key: str, record_id: str
    ) -> list[str]:
        """Return the parties that use the official place a source record names."""
        snapshot = current_accepted_snapshot(
            self._session, source_system_id, dataset_key, record_id
        )
        if snapshot is None or not snapshot.raw_payload:
            return []
        payload = dict(snapshot.raw_payload)
        address_ids: list[str] = []
        if dataset_key == "address_register":
            source_string = payload.get("source_string")
            if source_string:
                for address in self._session.execute(
                    select(registry.Address).where(
                        registry.Address.source_string == str(source_string)
                    )
                ).scalars().all():
                    address_ids.append(address.id)
                # An address belongs to a parcel, and the units of that parcel
                # carry the applications of the place.
                parcel_ids = [
                    str(row[0])
                    for row in self._session.execute(
                        select(registry.ParcelAddress.parcel_id).where(
                            registry.ParcelAddress.address_id.in_(address_ids)
                        )
                    ).all()
                ]
                if parcel_ids:
                    for row in self._session.execute(
                        select(registry.ParcelAddress.address_id).where(
                            registry.ParcelAddress.parcel_id.in_(parcel_ids)
                        )
                    ).all():
                        address_ids.append(str(row[0]))
        elif dataset_key == "parcel_register":
            number = payload.get("parcel_number")
            if number:
                parcel = self._session.execute(
                    select(registry.Parcel).where(
                        registry.Parcel.source_parcel_number == str(number)
                    )
                ).scalar_one_or_none()
                if parcel is not None:
                    for relation in self._session.execute(
                        select(registry.ParcelAddress).where(
                            registry.ParcelAddress.parcel_id == parcel.id
                        )
                    ).scalars().all():
                        address_ids.append(relation.address_id)
        if not address_ids:
            return []
        rows = self._session.execute(
            select(permit.ApplicationParty.party_id)
            .join(
                permit.ApplicationSite,
                permit.ApplicationSite.application_id == permit.ApplicationParty.application_id,
            )
            .where(permit.ApplicationSite.address_id.in_(address_ids))
        ).all()
        return [str(row[0]) for row in rows]

    # -------------------------------------------------------------------- views

    def case_view(self, case: change.ChangeCase) -> ChangeCaseView:
        """Return the view of one change case."""
        commands = self._session.execute(
            select(change.SourceCommand)
            .where(change.SourceCommand.change_case_id == case.id)
            .order_by(change.SourceCommand.id)
        ).scalars().all()
        dependencies = self._session.execute(
            select(change.ChangeDependency)
            .where(change.ChangeDependency.change_case_id == case.id)
            .order_by(change.ChangeDependency.id)
        ).scalars().all()
        tasks = self._session.execute(
            select(change.ReviewTask)
            .where(change.ReviewTask.change_case_id == case.id)
            .order_by(change.ReviewTask.id)
        ).scalars().all()
        return ChangeCaseView(
            change_case_id=case.id,
            target_type=case.target_type,
            target_id=case.target_id,
            change_kind=case.change_kind,
            title=case.title,
            status=case.status,
            old_value=dict(case.old_value or {}),
            proposed_value=dict(case.proposed_value or {}),
            reason=case.reason,
            evidence=list(case.evidence or []),
            requester_actor_id=case.requester_actor_id,
            assignee_actor_id=case.assignee_actor_id,
            approver_actor_id=case.approver_actor_id,
            destination=case.destination,
            expected_version=case.expected_version,
            due_at=case.due_at,
            version=case.version,
            scenario_id=case.scenario_id,
            created_at=case.created_at,
            allowed_transitions=list(permitted_targets(case.status, case.change_kind)),
            source_commands=[
                SourceCommandView(
                    source_command_id=command.id,
                    source_system_id=command.source_system_id,
                    operation=command.operation,
                    expected_source_version=command.expected_source_version,
                    accepted_source_version=command.accepted_source_version,
                    retry_key=command.retry_key,
                    status=command.status,
                    response=command.response,
                )
                for command in commands
            ],
            dependencies=[
                ChangeDependencyView(
                    dependency_id=dependency.id,
                    consumer_type=dependency.consumer_type,
                    consumer_id=dependency.consumer_id,
                    invalidation_state=dependency.invalidation_state,
                    task_id=dependency.task_id,
                )
                for dependency in dependencies
            ],
            tasks=[
                ReviewTaskView(
                    task_id=task.id,
                    task_type=task.task_type,
                    target_type=task.target_type,
                    target_id=task.target_id,
                    assignee_actor_id=task.assignee_actor_id,
                    status=task.status,
                    deduplication_key=task.deduplication_key,
                )
                for task in tasks
            ],
        )


__all__ = ["DISPATCHER_STATES", "REQUEST_ACTION", "ChangeService"]
