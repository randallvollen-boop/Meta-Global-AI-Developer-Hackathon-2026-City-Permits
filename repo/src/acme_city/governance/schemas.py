"""Command and view models for the governance service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GovernanceModel(BaseModel):
    """A model that ignores unknown request fields.

    A client-supplied role, actor or permission field is ignored rather than
    honoured: the server resolves the actor and the scope itself.
    """

    model_config = ConfigDict(extra="ignore")


class RegisterDatasetCommand(GovernanceModel):
    """Register or update a source dataset."""

    source_system_id: str
    dataset_key: str
    label: str
    domain_id: str | None = None
    accountable_owner_actor_id: str | None = None
    steward_queue_id: str | None = None
    system_custodian_actor_id: str | None = None
    authority_policy_id: str | None = None
    correction_route: str | None = None
    business_key_fields: list[str] = Field(default_factory=list)
    schema_version: str | None = None
    required_fields: dict[str, Any] = Field(default_factory=dict)
    allowed_values: dict[str, Any] = Field(default_factory=dict)
    date_meanings: dict[str, Any] = Field(default_factory=dict)
    field_classes: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class DatasetRegistrationView(GovernanceModel):
    """How a dataset is registered and whether it may publish."""

    contract_id: str
    source_system_id: str
    dataset_key: str
    label: str
    domain_id: str | None = None
    accountable_owner_actor_id: str | None = None
    steward_queue_id: str | None = None
    system_custodian_actor_id: str | None = None
    authority_policy_id: str | None = None
    correction_route: str | None = None
    registration_state: str = "complete"
    publishable: bool = False
    missing_bindings: list[str] = Field(default_factory=list)
    version: int = 1


class ReassignStewardCommand(GovernanceModel):
    """Move a responsibility to another actor."""

    domain_id: str
    responsibility: str = "steward"
    new_actor_id: str
    reason: str
    expected_version: int | None = None


class DeactivateStewardCommand(GovernanceModel):
    """Deactivate a steward, reassigning active work first."""

    actor_id: str
    reason: str
    reassign_domain_id: str | None = None
    reassign_to_actor_id: str | None = None
    expected_version: int | None = None


class AssignmentView(GovernanceModel):
    """One effective-dated assignment."""

    assignment_id: str
    subject_type: str
    subject_id: str
    responsibility: str
    actor_id: str | None = None
    queue_id: str | None = None
    effective_from: datetime
    effective_to: datetime | None = None
    supersedes_assignment_id: str | None = None
    superseded_by_assignment_id: str | None = None
    version: int = 1


class PreviewAuthorityChangeCommand(GovernanceModel):
    """Describe a proposed change of field authority."""

    policy_id: str
    field_group: str
    domain_id: str | None = None
    authoritative_source_system_id: str | None = None
    authoritative_dataset_key: str | None = None
    change_destination: str
    user_action: str
    requires_source_ack: bool = True
    decision_relevant: bool = False
    reason: str | None = None


class AuthorityImpactPreview(GovernanceModel):
    """What a proposed authority change would affect."""

    policy_id: str
    field_group: str
    domain_id: str | None = None
    impacted_datasets: list[str] = Field(default_factory=list)
    impacted_applications: list[str] = Field(default_factory=list)
    impacted_cases: list[str] = Field(default_factory=list)
    impacted_permits: list[str] = Field(default_factory=list)
    current_policy_version: int = 1
    requires_owner_approval: bool = True
    approver_actor_id: str | None = None


class PublishAuthorityChangeCommand(GovernanceModel):
    """Publish an authority policy version after an impact preview."""

    policy_id: str
    approver_actor_id: str
    expected_version: int
    reason: str
    field_group: str | None = None
    domain_id: str | None = None
    authoritative_source_system_id: str | None = None
    authoritative_dataset_key: str | None = None
    change_destination: str | None = None
    user_action: str | None = None
    requires_source_ack: bool = True
    decision_relevant: bool = False


class AuthorityPolicyView(GovernanceModel):
    """One authority policy as the service reports it."""

    policy_id: str
    field_group: str
    domain_id: str | None = None
    authoritative_source_system_id: str | None = None
    authoritative_dataset_key: str | None = None
    change_destination: str
    user_action: str
    requires_source_ack: bool = True
    decision_relevant: bool = False
    status: str = "proposed_demo_default"
    effective_from: datetime | None = None
    approver_actor_id: str | None = None
    version: int = 1


class EscalateIssueCommand(GovernanceModel):
    """Route a dispute to the accountable owner of a domain."""

    domain_id: str
    subject_type: str
    subject_id: str
    issue_type: str
    description: str
    reason: str | None = None


class IssueView(GovernanceModel):
    """A governance issue and who now owns it."""

    issue_id: str
    subject_type: str
    subject_id: str
    issue_type: str
    description: str
    responsible_queue_id: str | None = None
    assigned_actor_id: str | None = None
    blocking: bool = True
    status: str = "open"
    version: int = 1


__all__ = [
    "AssignmentView",
    "AuthorityImpactPreview",
    "AuthorityPolicyView",
    "DatasetRegistrationView",
    "DeactivateStewardCommand",
    "EscalateIssueCommand",
    "GovernanceModel",
    "IssueView",
    "PreviewAuthorityChangeCommand",
    "PublishAuthorityChangeCommand",
    "RegisterDatasetCommand",
    "ReassignStewardCommand",
]
