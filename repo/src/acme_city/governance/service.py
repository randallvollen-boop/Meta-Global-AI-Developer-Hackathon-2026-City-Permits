"""Governance registration, assignments, escalation and authority policy.

The service owns the governed transitions: it registers datasets and their
responsibility, resolves the current responsibility through effective-dated
assignments, previews the impact of an authority change before it is
published, and appends an audit event for every accepted mutation inside the
caller's transaction.
"""
# REQUIRES: GOV-01, GOV-02, GOV-03, GOV-05, GOV-06, GOV-07
# Registration and the publication gate, effective-dated assignment resolution,
# steward deactivation and reassignment, owner escalation and the authority impact
# preview are implemented here.


from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import (
    ConflictError,
    GovernanceGateError,
    IncompleteRegistrationError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from acme_city.core.ids import new_id
from acme_city.core.results import VersionedResult
from acme_city.governance.schemas import (
    AssignmentView,
    AuthorityImpactPreview,
    AuthorityPolicyView,
    DatasetRegistrationView,
    DeactivateStewardCommand,
    EscalateIssueCommand,
    IssueView,
    PreviewAuthorityChangeCommand,
    PublishAuthorityChangeCommand,
    RegisterDatasetCommand,
    ReassignStewardCommand,
)
from acme_city.persistence.models import change, governance, permit, source

#: The bindings a dataset needs before it may publish trusted facts.
REQUIRED_DATASET_BINDINGS: tuple[str, ...] = (
    "source_system_id",
    "source_dataset_id",
    "domain",
    "accountable_owner",
    "active_primary_steward",
    "active_delegate",
    "escalation_owner",
    "system_custodian",
    "data_contract",
    "field_authority_policy",
    "correction_route",
)

_ASSIGNMENT_CLOSED_STATES = {"closed", "rejected", "synchronization_failed"}


class GovernanceService:
    """Governed maintenance of ownership, assignment and authority."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    # ------------------------------------------------------------ registration

    def missing_bindings(self, contract: governance.SourceContract) -> list[str]:
        """Return the required bindings a registration still lacks."""
        missing: list[str] = []
        if not contract.source_system_id:
            missing.append("source_system_id")
        if not contract.dataset_key:
            missing.append("source_dataset_id")
        if not contract.domain_id:
            missing.append("domain")
        if not contract.accountable_owner_actor_id:
            missing.append("accountable_owner")
        queue = self._queue(contract.steward_queue_id)
        if queue is None or not queue.primary_actor_id:
            missing.append("active_primary_steward")
        if queue is None or not queue.delegate_actor_id:
            missing.append("active_delegate")
        if queue is None or not queue.escalation_actor_id:
            missing.append("escalation_owner")
        if not contract.system_custodian_actor_id:
            missing.append("system_custodian")
        if not contract.schema_version or not contract.business_key_fields:
            missing.append("data_contract")
        if not contract.authority_policy_id:
            missing.append("field_authority_policy")
        if not contract.correction_route:
            missing.append("correction_route")
        return missing

    def _queue(self, queue_id: str | None) -> governance.StewardQueue | None:
        if not queue_id:
            return None
        return self._session.execute(
            select(governance.StewardQueue).where(governance.StewardQueue.queue_id == queue_id)
        ).scalar_one_or_none()

    def register_dataset(
        self, command: RegisterDatasetCommand, actor: ActorContext
    ) -> VersionedResult[DatasetRegistrationView]:
        """Register a dataset with its responsibility, or record what is missing."""
        self._permissions.authorize(
            actor,
            "governance.dataset.register",
            ResourceContext(domain_id=command.domain_id, record_type="source_dataset"),
        )
        contract = self._session.execute(
            select(governance.SourceContract).where(
                governance.SourceContract.source_system_id == command.source_system_id,
                governance.SourceContract.dataset_key == command.dataset_key,
            )
        ).scalar_one_or_none()
        if contract is None:
            contract = governance.SourceContract(
                id=f"contract_{command.source_system_id}_{command.dataset_key}",
                contract_id=f"contract_{command.source_system_id}_{command.dataset_key}",
                source_system_id=command.source_system_id,
                dataset_key=command.dataset_key,
                label=command.label,
            )
            self._session.add(contract)

        contract.label = command.label
        contract.domain_id = command.domain_id
        contract.accountable_owner_actor_id = command.accountable_owner_actor_id
        contract.steward_queue_id = command.steward_queue_id
        contract.system_custodian_actor_id = command.system_custodian_actor_id
        contract.authority_policy_id = command.authority_policy_id
        contract.correction_route = command.correction_route
        contract.business_key_fields = list(command.business_key_fields)
        contract.schema_version = command.schema_version
        contract.required_fields = dict(command.required_fields)
        contract.allowed_values = dict(command.allowed_values)
        contract.date_meanings = dict(command.date_meanings)
        contract.field_classes = dict(command.field_classes)

        self._session.flush()
        missing = self.missing_bindings(contract)
        contract.registration_state = "incomplete" if missing else "complete"
        contract.registered_at = self._now
        contract.version = contract.version + 1
        self._session.flush()

        event = self._audit.append(
            action="governance.dataset.register",
            actor=actor,
            target_type="source_dataset",
            target_id=contract.contract_id,
            before_version=contract.version - 1,
            after_version=contract.version,
            reason=command.reason,
            references=[contract.source_system_id, contract.dataset_key],
        )
        view = self.registration_view(contract)
        return VersionedResult(value=view, version=contract.version, audit_event_id=event.id)

    def registration_view(self, contract: governance.SourceContract) -> DatasetRegistrationView:
        """Return the registration view of a contract."""
        missing = self.missing_bindings(contract)
        return DatasetRegistrationView(
            contract_id=contract.contract_id,
            source_system_id=contract.source_system_id,
            dataset_key=contract.dataset_key,
            label=contract.label,
            domain_id=contract.domain_id,
            accountable_owner_actor_id=contract.accountable_owner_actor_id,
            steward_queue_id=contract.steward_queue_id,
            system_custodian_actor_id=contract.system_custodian_actor_id,
            authority_policy_id=contract.authority_policy_id,
            correction_route=contract.correction_route,
            registration_state=contract.registration_state,
            publishable=not missing,
            missing_bindings=missing,
            version=contract.version,
        )

    def list_registrations(self) -> list[DatasetRegistrationView]:
        """Return every registered dataset."""
        contracts = self._session.execute(
            select(governance.SourceContract).order_by(governance.SourceContract.contract_id)
        ).scalars().all()
        return [self.registration_view(contract) for contract in contracts]

    def publish_dataset(
        self, dataset_key: str, actor: ActorContext
    ) -> VersionedResult[DatasetRegistrationView]:
        """Publish a registered dataset, refusing an incomplete registration."""
        contract = self._session.execute(
            select(governance.SourceContract).where(
                governance.SourceContract.dataset_key == dataset_key
            )
        ).scalar_one_or_none()
        if contract is None:
            raise NotFoundError(f"no dataset is registered under {dataset_key!r}")
        self._permissions.authorize(
            actor,
            "governance.dataset.register",
            ResourceContext(
                domain_id=contract.domain_id,
                record_type="source_dataset",
                record_ids=(dataset_key,),
            ),
        )
        missing = self.missing_bindings(contract)
        if missing:
            raise IncompleteRegistrationError(
                f"the dataset {dataset_key!r} cannot publish trusted facts yet",
                dataset_key=dataset_key,
                missing_bindings=missing,
            )
        before_version = contract.version
        contract.registration_state = "complete"
        contract.version = contract.version + 1
        event = self._audit.append(
            action="governance.dataset.publish",
            actor=actor,
            target_type="source_dataset",
            target_id=contract.contract_id,
            before_version=before_version,
            after_version=contract.version,
            references=[dataset_key],
        )
        return VersionedResult(
            value=self.registration_view(contract),
            version=contract.version,
            audit_event_id=event.id,
        )

    # ------------------------------------------------------------ assignments

    def current_assignments(self, domain_id: str | None = None) -> list[AssignmentView]:
        """Return the assignments that are effective now."""
        statement = select(governance.Assignment).where(
            governance.Assignment.effective_from <= self._now,
            (
                governance.Assignment.effective_to.is_(None)
                | (governance.Assignment.effective_to > self._now)
            ),
        )
        if domain_id is not None:
            statement = statement.where(governance.Assignment.subject_id == domain_id)
        assignments = self._session.execute(statement.order_by(governance.Assignment.id)).scalars().all()
        return [self.assignment_view(assignment) for assignment in assignments]

    def assignment_view(self, assignment: governance.Assignment) -> AssignmentView:
        """Return the view of one assignment."""
        return AssignmentView(
            assignment_id=assignment.id,
            subject_type=assignment.subject_type,
            subject_id=assignment.subject_id,
            responsibility=assignment.responsibility,
            actor_id=assignment.actor_id,
            queue_id=assignment.queue_id,
            effective_from=assignment.effective_from,
            effective_to=assignment.effective_to,
            supersedes_assignment_id=assignment.supersedes_assignment_id,
            superseded_by_assignment_id=assignment.superseded_by_assignment_id,
            version=assignment.version,
        )

    def _current_assignment(
        self, domain_id: str, responsibility: str
    ) -> governance.Assignment | None:
        return self._session.execute(
            select(governance.Assignment)
            .where(
                governance.Assignment.subject_type == "domain",
                governance.Assignment.subject_id == domain_id,
                governance.Assignment.responsibility == responsibility,
                governance.Assignment.effective_from <= self._now,
                (
                    governance.Assignment.effective_to.is_(None)
                    | (governance.Assignment.effective_to > self._now)
                ),
            )
            .order_by(governance.Assignment.effective_from.desc())
        ).scalars().first()

    def reassign_steward(
        self, command: ReassignStewardCommand, actor: ActorContext
    ) -> VersionedResult[AssignmentView]:
        """Move a responsibility to another actor, keeping the earlier record."""
        self._permissions.authorize(
            actor,
            "governance.assignment.manage",
            ResourceContext(domain_id=command.domain_id, record_type="assignment"),
        )
        current = self._current_assignment(command.domain_id, command.responsibility)
        if current is None:
            raise NotFoundError(
                f"no effective {command.responsibility} assignment exists for {command.domain_id!r}"
            )
        replacement = self._session.execute(
            select(governance.Actor).where(governance.Actor.actor_id == command.new_actor_id)
        ).scalar_one_or_none()
        if replacement is None:
            raise NotFoundError(f"unknown actor {command.new_actor_id!r}")
        if not replacement.active:
            raise ValidationError(f"actor {command.new_actor_id!r} is not active")
        if command.expected_version is not None and current.version != command.expected_version:
            raise ConflictError(
                "the assignment changed since it was read",
                expected_version=command.expected_version,
                current_version=current.version,
            )

        before_version = current.version
        current.effective_to = self._now
        current.version = current.version + 1

        assignment = governance.Assignment(
            id=new_id("assign"),
            subject_type="domain",
            subject_id=command.domain_id,
            responsibility=command.responsibility,
            actor_id=command.new_actor_id,
            queue_id=current.queue_id,
            effective_from=self._now,
            effective_to=None,
            supersedes_assignment_id=current.id,
            reason=command.reason,
            source="governance_service",
        )
        current.superseded_by_assignment_id = assignment.id
        self._session.add(assignment)
        self._session.flush()

        event = self._audit.append(
            action="governance.assignment.reassign",
            actor=actor,
            target_type="assignment",
            target_id=assignment.id,
            before_version=before_version,
            after_version=assignment.version,
            reason=command.reason,
            references=[command.domain_id, current.id, command.new_actor_id],
        )
        return VersionedResult(
            value=self.assignment_view(assignment),
            version=assignment.version,
            audit_event_id=event.id,
        )

    def active_work_for(self, actor_id: str) -> list[str]:
        """Return the identifiers of the open work assigned to an actor."""
        identifiers: list[str] = []
        cases = self._session.execute(
            select(change.ChangeCase).where(
                change.ChangeCase.assignee_actor_id == actor_id,
                change.ChangeCase.status.not_in(_ASSIGNMENT_CLOSED_STATES),
            )
        ).scalars().all()
        identifiers.extend(case.id for case in cases)
        tasks = self._session.execute(
            select(change.ReviewTask).where(
                change.ReviewTask.assignee_actor_id == actor_id,
                change.ReviewTask.status == "open",
            )
        ).scalars().all()
        identifiers.extend(task.id for task in tasks)
        return identifiers

    def deactivate_steward(
        self, command: DeactivateStewardCommand, actor: ActorContext
    ) -> VersionedResult[ActorContext]:
        """Deactivate a steward, refusing when active work has no reassignment."""
        target = self._session.execute(
            select(governance.Actor).where(governance.Actor.actor_id == command.actor_id)
        ).scalar_one_or_none()
        if target is None:
            raise NotFoundError(f"unknown actor {command.actor_id!r}")
        if not target.active:
            raise ConflictError(f"actor {command.actor_id!r} is already deactivated")

        responsible_domains = sorted(
            {
                assignment.subject_id
                for assignment in self._session.execute(
                    select(governance.Assignment).where(
                        governance.Assignment.actor_id == command.actor_id,
                        governance.Assignment.effective_to.is_(None),
                    )
                ).scalars().all()
            }
        )
        if command.reassign_domain_id:
            responsible_domains = sorted(
                set(responsible_domains) | {command.reassign_domain_id}
            )
        if not responsible_domains:
            responsible_domains = [command.reassign_domain_id]
        for domain_id in responsible_domains:
            self._permissions.authorize(
                actor,
                "governance.assignment.manage",
                ResourceContext(
                    domain_id=domain_id, record_type="actor", record_ids=(command.actor_id,)
                ),
            )

        outstanding = self.active_work_for(command.actor_id)
        if outstanding and not (command.reassign_domain_id and command.reassign_to_actor_id):
            raise ConflictError(
                "the steward still holds active work; reassign it before deactivating",
                code="active_work_conflict",
                active_work=outstanding,
                actor_id=command.actor_id,
            )

        reassigned: AssignmentView | None = None
        if command.reassign_domain_id and command.reassign_to_actor_id:
            reassigned = self.reassign_steward(
                ReassignStewardCommand(
                    domain_id=command.reassign_domain_id,
                    responsibility="steward",
                    new_actor_id=command.reassign_to_actor_id,
                    reason=command.reason,
                ),
                actor,
            ).value

        ended = self._session.execute(
            select(governance.Assignment).where(
                governance.Assignment.actor_id == command.actor_id,
                governance.Assignment.effective_to.is_(None),
                governance.Assignment.effective_from <= self._now,
            )
        ).scalars().all()
        for assignment in ended:
            assignment.effective_to = self._now
            assignment.version = assignment.version + 1

        target.active = False
        target.deactivated_at = self._now
        target.deactivated_reason = command.reason

        event = self._audit.append(
            action="governance.actor.deactivate",
            actor=actor,
            target_type="actor",
            target_id=target.actor_id,
            reason=command.reason,
            references=[*outstanding, *( [reassigned.assignment_id] if reassigned else [])],
        )
        context = ActorContext(
            actor_id=target.actor_id,
            role_ids=frozenset(),
            domain_scope=frozenset(),
            record_scope=frozenset(),
            active=False,
        )
        return VersionedResult(value=context, version=1, audit_event_id=event.id)

    # ------------------------------------------------------------ authority

    def _policy(self, policy_id: str) -> governance.AuthorityPolicy:
        policy = self._session.execute(
            select(governance.AuthorityPolicy).where(
                governance.AuthorityPolicy.policy_id == policy_id
            )
        ).scalar_one_or_none()
        if policy is None:
            raise NotFoundError(f"unknown authority policy {policy_id!r}")
        return policy

    def preview_authority_change(
        self, command: PreviewAuthorityChangeCommand, actor: ActorContext
    ) -> AuthorityImpactPreview:
        """Show which datasets and cases an authority change would affect."""
        policy = self._policy(command.policy_id)
        self._permissions.authorize(
            actor,
            "governance.authority_policy.manage",
            ResourceContext(
                domain_id=command.domain_id or policy.domain_id,
                record_type="authority_policy",
                record_ids=(command.policy_id,),
            ),
        )

        contracts = self._session.execute(
            select(governance.SourceContract).where(
                governance.SourceContract.authority_policy_id == command.policy_id
            )
        ).scalars().all()
        impacted_datasets = sorted(contract.dataset_key for contract in contracts)
        if command.domain_id:
            domain_contracts = self._session.execute(
                select(governance.SourceContract).where(
                    governance.SourceContract.domain_id == command.domain_id
                )
            ).scalars().all()
            impacted_datasets = sorted(
                set(impacted_datasets) | {contract.dataset_key for contract in domain_contracts}
            )

        application_numbers: set[str] = set()
        for contract in contracts:
            snapshots = self._session.execute(
                select(source.SourceSnapshot).where(
                    source.SourceSnapshot.source_dataset_id == contract.dataset_key
                )
            ).scalars().all()
            for snapshot in snapshots:
                if snapshot.source_record_id.startswith("PER-APP-"):
                    application_numbers.add(snapshot.source_record_id.removeprefix("PER-APP-"))
        applications = sorted(application_numbers)
        permit_rows = self._session.execute(select(permit.Permit)).scalars().all()
        permits = sorted(
            row.permit_number
            for row in permit_rows
            if row.snapshot.get("application_number") in application_numbers
        )

        approver = policy.approver_actor_id
        if command.domain_id:
            domain = self._session.execute(
                select(governance.Domain).where(
                    governance.Domain.domain_id == command.domain_id
                )
            ).scalar_one_or_none()
            if domain is not None and domain.accountable_owner_actor_id:
                approver = domain.accountable_owner_actor_id

        return AuthorityImpactPreview(
            policy_id=policy.policy_id,
            field_group=command.field_group,
            domain_id=command.domain_id,
            impacted_datasets=impacted_datasets,
            impacted_applications=applications,
            impacted_cases=applications,
            impacted_permits=permits,
            current_policy_version=policy.version,
            requires_owner_approval=approver is not None,
            approver_actor_id=approver,
        )

    def publish_authority_change(
        self, command: PublishAuthorityChangeCommand, actor: ActorContext
    ) -> VersionedResult[AuthorityPolicyView]:
        """Publish an authority policy version after its impact preview."""
        policy = self._policy(command.policy_id)
        self._permissions.authorize(
            actor,
            "governance.authority_policy.publish",
            ResourceContext(
                domain_id=policy.domain_id,
                record_type="authority_policy",
                record_ids=(command.policy_id,),
            ),
        )
        if policy.version != command.expected_version:
            raise ConflictError(
                "the authority policy changed since it was read",
                expected_version=command.expected_version,
                current_version=policy.version,
            )
        if command.approver_actor_id == actor.actor_id:
            raise PermissionDeniedError(
                "the author of an authority policy may not approve it",
                policy_id=command.policy_id,
                actor_id=actor.actor_id,
            )
        approver = self._session.execute(
            select(governance.Actor).where(governance.Actor.actor_id == command.approver_actor_id)
        ).scalar_one_or_none()
        if approver is None:
            raise NotFoundError(f"unknown approver {command.approver_actor_id!r}")
        if not approver.active:
            raise ValidationError(f"approver {command.approver_actor_id!r} is not active")

        before_version = policy.version
        if command.field_group:
            policy.field_group = command.field_group
        if command.change_destination:
            policy.change_destination = command.change_destination
        if command.user_action:
            policy.user_action = command.user_action
        if command.authoritative_source_system_id:
            policy.authoritative_source_system_id = command.authoritative_source_system_id
        if command.authoritative_dataset_key:
            policy.authoritative_dataset_key = command.authoritative_dataset_key
        if command.domain_id:
            policy.domain_id = command.domain_id
        policy.requires_source_ack = command.requires_source_ack
        policy.decision_relevant = command.decision_relevant
        policy.status = "published"
        policy.approver_actor_id = command.approver_actor_id
        policy.published_at = self._now
        policy.version = policy.version + 1

        event = self._audit.append(
            action="governance.authority_policy.publish",
            actor=actor,
            target_type="authority_policy",
            target_id=policy.policy_id,
            before_version=before_version,
            after_version=policy.version,
            reason=command.reason,
            references=[command.approver_actor_id],
        )
        return VersionedResult(
            value=self.policy_view(policy),
            version=policy.version,
            audit_event_id=event.id,
        )

    def policy_view(self, policy: governance.AuthorityPolicy) -> AuthorityPolicyView:
        """Return the view of one authority policy."""
        return AuthorityPolicyView(
            policy_id=policy.policy_id,
            field_group=policy.field_group,
            domain_id=policy.domain_id,
            authoritative_source_system_id=policy.authoritative_source_system_id,
            authoritative_dataset_key=policy.authoritative_dataset_key,
            change_destination=policy.change_destination,
            user_action=policy.user_action,
            requires_source_ack=policy.requires_source_ack,
            decision_relevant=policy.decision_relevant,
            status=policy.status,
            effective_from=policy.effective_from,
            approver_actor_id=policy.approver_actor_id,
            version=policy.version,
        )

    # ------------------------------------------------------------ escalation

    def escalate_issue(
        self, command: EscalateIssueCommand, actor: ActorContext
    ) -> VersionedResult[IssueView]:
        """Route a dispute to the accountable owner of the domain."""
        self._permissions.authorize(
            actor,
            "correction.request.submit",
            ResourceContext(domain_id=command.domain_id, record_type="governance_issue"),
        )
        domain = self._session.execute(
            select(governance.Domain).where(governance.Domain.domain_id == command.domain_id)
        ).scalar_one_or_none()
        if domain is None:
            raise NotFoundError(f"unknown domain {command.domain_id!r}")
        owner = domain.accountable_owner_actor_id
        if not owner:
            raise GovernanceGateError(
                f"the domain {command.domain_id!r} has no accountable owner to escalate to"
            )
        issue = change.GovernanceIssue(
            id=new_id("issue"),
            subject_type=command.subject_type,
            subject_id=command.subject_id,
            issue_type=command.issue_type,
            description=command.description,
            responsible_queue_id=domain.steward_queue_id,
            assigned_actor_id=owner,
            blocking=True,
            status="open",
        )
        self._session.add(issue)
        self._session.flush()
        event = self._audit.append(
            action="governance.issue.escalate",
            actor=actor,
            target_type="governance_issue",
            target_id=issue.id,
            after_version=issue.version,
            reason=command.reason,
            references=[command.domain_id, owner],
        )
        view = IssueView(
            issue_id=issue.id,
            subject_type=issue.subject_type,
            subject_id=issue.subject_id,
            issue_type=issue.issue_type,
            description=issue.description,
            responsible_queue_id=issue.responsible_queue_id,
            assigned_actor_id=issue.assigned_actor_id,
            blocking=issue.blocking,
            status=issue.status,
            version=issue.version,
        )
        return VersionedResult(value=view, version=issue.version, audit_event_id=event.id)

    # ------------------------------------------------------------ helpers

    def responsibility_panel(self, domain_id: str) -> dict[str, object]:
        """Return the resolved responsibility for a domain."""
        assignments = self.current_assignments(domain_id)
        domain = self._session.execute(
            select(governance.Domain).where(governance.Domain.domain_id == domain_id)
        ).scalar_one_or_none()
        queue = self._queue(domain.steward_queue_id if domain else None)
        return {
            "domain_id": domain_id,
            "owner": domain.accountable_owner_actor_id if domain else None,
            "steward": next(
                (a.actor_id for a in assignments if a.responsibility == "steward"), None
            ),
            "source": domain.default_source_system_id if domain else None,
            "change_this_in": None,
            "version": domain.version if domain else None,
            "assignments": [assignment.model_dump(mode="json") for assignment in assignments],
            "queue": queue.queue_id if queue else None,
        }


__all__ = ["GovernanceService", "REQUIRED_DATASET_BINDINGS"]
