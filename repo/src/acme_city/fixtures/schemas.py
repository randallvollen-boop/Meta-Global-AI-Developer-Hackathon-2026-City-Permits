"""Validation models for the committed fixture and configuration documents.

Every committed document is validated before it is inserted into the database.
A fixture that does not validate is a build error, not a runtime surprise.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from acme_city.core.clock import ensure_utc


class StrictModel(BaseModel):
    """A model that rejects unknown keys in a data row."""

    model_config = ConfigDict(extra="forbid")


class CatalogModel(BaseModel):
    """A model for a configuration document.

    A configuration document carries descriptive metadata next to its data, so
    extra keys are preserved rather than rejected.
    """

    model_config = ConfigDict(extra="allow")


class TimestampedModel(StrictModel):
    """A model whose timestamps are timezone-aware UTC or explicitly null."""

    @field_validator(
        "source_updated_at", "effective_from", "effective_to", "ingested_at", mode="before",
        check_fields=False,
    )
    @classmethod
    def _timestamps_are_aware(cls, value: Any) -> Any:
        if isinstance(value, str):
            return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        return value


class RoleFixture(StrictModel):
    role_id: str
    label: str
    boundary: str = ""
    permission_ids: list[str] = Field(default_factory=list)


class GrantFixture(StrictModel):
    permission_id: str
    domains: list[str] = Field(default_factory=list)
    record_scope: list[str] = Field(default_factory=list)
    source: str = "explicit"


class PersonaFixture(StrictModel):
    """One selectable human persona."""

    actor_id: str
    label: str
    selectable: bool = True
    source_role_ids: list[str] = Field(default_factory=list)
    domain_scope: list[str] = Field(default_factory=list)
    record_scope: list[str] = Field(default_factory=list)
    responsibility: str = ""
    fictional: bool = True
    active_when_seeded: bool = True
    grants: list[GrantFixture] = Field(default_factory=list)
    permission_resolution: str = ""


class ServiceIdentityFixture(StrictModel):
    """A nonselectable identity that carries an organizational binding."""

    actor_id: str
    label: str
    selectable: bool = False
    role_ids: list[str] = Field(default_factory=list)
    domain_scope: list[str] = Field(default_factory=list)
    system_scope: list[str] = Field(default_factory=list)
    record_scope: list[str] = Field(default_factory=list)
    fictional: bool = True
    active_when_seeded: bool = True
    grants: list[GrantFixture] = Field(default_factory=list)
    permission_resolution: str = ""


class ActorCatalog(CatalogModel):
    """The role templates, the selectable personas and the service identities."""

    catalog_version: str
    roles: list[RoleFixture]
    personas: list[PersonaFixture] = Field(default_factory=list)
    service_identities: list[ServiceIdentityFixture] = Field(default_factory=list)


class PermissionEntry(StrictModel):
    permission_id: str
    action: str
    category: str = "general"
    description: str = ""
    sensitive: bool = False


class PermissionCatalog(CatalogModel):
    catalog_version: str
    permissions: list[PermissionEntry]
    role_grants: dict[str, list[str]] = Field(default_factory=dict)


class DomainFixture(StrictModel):
    domain_id: str
    label: str
    accountable_owner_actor_id: str | None = None
    accountable_owner_role_label: str | None = None
    owner_strategy: str | None = None
    steward_queue_id: str | None = None
    steward_strategy: str | None = None
    steward_queue_strategy: str | None = None
    system_custodian_actor_id: str | None = None
    default_source_system_id: str | None = None
    default_dataset_key: str | None = None
    authoritative_component_id: str | None = None
    cross_domain_dispute_actor_id: str | None = None
    assignment_effective_from_basis: str | None = None
    assignment_effective_to: str | None = None
    record_assignment_resolution: str | None = None


class QueueFixture(StrictModel):
    queue_id: str
    domain_id: str
    primary_actor_id: str | None = None
    delegate_actor_id: str | None = None
    escalation_actor_id: str | None = None
    cross_domain_escalation_actor_id: str | None = None
    first_review_target: dict[str, Any] = Field(default_factory=dict)


class DomainCatalog(CatalogModel):
    catalog_version: str
    domains: list[DomainFixture]
    steward_queues: list[QueueFixture]
    assignment_rules: list[str] = Field(default_factory=list)
    current_responsibility_display: list[str] = Field(default_factory=list)
    registration_publication_gate: dict[str, Any] = Field(default_factory=dict)
    correction_paths: dict[str, Any] = Field(default_factory=dict)


class ContractFixture(StrictModel):
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
    business_key_fields: list[str] = Field(default_factory=list)
    schema_version: str | None = None
    required_fields: dict[str, Any] = Field(default_factory=dict)
    allowed_values: dict[str, Any] = Field(default_factory=dict)
    date_meanings: dict[str, Any] = Field(default_factory=dict)
    field_classes: dict[str, Any] = Field(default_factory=dict)
    registration_state: str = "complete"
    fictional_demo: bool = True


class ContractCatalog(CatalogModel):
    catalog_version: str
    source_contracts: list[ContractFixture]


class CorrectionRequestFixture(StrictModel):
    model_config = ConfigDict(extra="allow")
    action_permission: str | None = None
    proposed_role_candidates: list[str] = Field(default_factory=list)
    permitted_effect: str | None = None


class PolicyFixture(StrictModel):
    model_config = ConfigDict(extra="allow")
    policy_id: str
    field_group: str
    domain_id: str | None = None
    authoritative_source_system_id: str | None = None
    authoritative_component_id: str | None = None
    authoritative_dataset_key: str | None = None
    change_destination: str
    user_action: str
    requires_source_ack_for_factual_correction: bool = True
    decision_relevant_by_default: bool = False
    status: str = "proposed_demo_default"
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    approver_actor_id: str | None = None
    authoritative_action_actor_roles: list[str] = Field(default_factory=list)
    correction_request_submission: dict[str, Any] = Field(default_factory=dict)


class PolicyCatalog(CatalogModel):
    catalog_version: str
    authority_policies: list[PolicyFixture]


class PermitTypeFixture(StrictModel):
    permit_type_id: str
    key: str
    label: str
    review_route: str
    required_fields: list[str] = Field(default_factory=list)
    required_documents: list[str] = Field(default_factory=list)
    source_mapping: dict[str, Any] = Field(default_factory=dict)
    #: The review area the intake router sends a ready case to.
    review_area: str | None = None
    #: ``simple``, ``with_plans`` or ``formal_review``.
    process_category: str | None = None
    #: A discretionary type is always held for a person or a board.
    discretionary: bool = False
    description: str = ""
    #: The fee schedule key that applies to this type.
    fee_schedule_key: str | None = None
    #: The fictional service target of the type, in whole days.  It is the
    #: number of days the City aims to review a case of this type in; it is
    #: a demonstration figure and never a promise to an applicant.
    service_target_days: int = Field(default=0, ge=0)


class RuleFixture(StrictModel):
    rule_id: str
    version: int = 1
    permit_type: str | None = None
    kind: str = "executable"
    title: str
    citation: str
    field_path: str | None = None
    operator: str | None = None
    limit_value: str | None = None
    on_violate: str | None = None
    condition: dict[str, Any] | None = None
    message: str | None = None
    condition_note: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    status: str = "draft"
    author_actor_id: str | None = None
    approver_actor_id: str | None = None
    source_mapping: dict[str, Any] = Field(default_factory=dict)


class FeeScheduleFixture(StrictModel):
    fee_schedule_id: str
    version_label: str
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    currency: str = "USD"
    definition: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"
    author_actor_id: str | None = None
    approver_actor_id: str | None = None
    source_mapping: dict[str, Any] = Field(default_factory=dict)


class RuleCatalog(CatalogModel):
    catalog_version: str
    permit_types: list[PermitTypeFixture]
    rules: list[RuleFixture]
    fee_schedules: list[FeeScheduleFixture]


class ScenarioFixture(StrictModel):
    scenario_id: str
    title: str
    condition: str
    related_records: list[str] = Field(default_factory=list)
    starting_state: str = ""


class ReasonCodeFixture(StrictModel):
    code: str
    label: str
    description: str = ""
    #: The use the code may serve: ``return``, ``denial``, ``waiver``,
    #: ``revision`` or ``archive``.
    code_type: str = "return"


class DemoConfig(CatalogModel):
    config_version: str
    fixture_version: str
    demo_timezone: str = "America/New_York"
    assignment_epoch: datetime | None = None
    policy_epoch: datetime | None = None
    session: dict[str, Any] = Field(default_factory=dict)
    reset: dict[str, Any] = Field(default_factory=dict)
    scenarios: list[ScenarioFixture] = Field(default_factory=list)
    reason_codes: list[ReasonCodeFixture] = Field(default_factory=list)


class PartyFixture(StrictModel):
    party_id: str
    party_type: str
    display_name: str
    legal_name: str | None = None
    status: str = "active"
    scenario_id: str | None = None


class AliasFixture(StrictModel):
    alias_id: str
    party_id: str
    alias_value: str
    alias_type: str = "alias"
    source_record_ref: str | None = None
    scenario_id: str | None = None


class ContactFixture(StrictModel):
    contact_id: str
    party_id: str
    contact_type: str
    value: str
    verification_state: str = "unverified"
    source_record_ref: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    scenario_id: str | None = None


class ParcelFixture(StrictModel):
    parcel_id: str
    jurisdiction_id: str
    source_parcel_number: str
    status: str = "active"
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    source_record_ref: str | None = None
    scenario_id: str | None = None


class AddressFixture(StrictModel):
    address_id: str
    street_number: str | None = None
    street_name: str | None = None
    street_type: str | None = None
    unit_type: str | None = None
    unit_number: str | None = None
    municipality: str | None = None
    region: str | None = None
    postcode: str | None = None
    source_string: str | None = None
    status: str = "active"
    source_record_ref: str | None = None
    scenario_id: str | None = None


class ParcelAddressFixture(StrictModel):
    relationship_id: str
    parcel_id: str
    address_id: str
    relationship_type: str = "official"
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    evidence_ref: str | None = None
    scenario_id: str | None = None


class CredentialFixture(StrictModel):
    credential_id: str
    holder_party_id: str
    credential_type: str
    issuing_authority_id: str
    number: str
    status: str = "active"
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    verified_at: datetime | None = None
    source_system_id: str | None = None
    source_record_id: str | None = None
    scenario_id: str | None = None


class FinanceAccountFixture(StrictModel):
    account_id: str
    source_account_id: str
    source_system_id: str = "erp_finance"
    party_id: str | None = None
    account_role: str = "payer"
    source_version: str | None = None
    link_status: str = "unlinked"
    link_decision: str | None = None
    scenario_id: str | None = None


class ApplicationFixture(StrictModel):
    application_id: str
    source_application_number: str
    permit_type: str
    initial_submitted_at: datetime | None = None
    revision_submitted_at: datetime | None = None
    status: str = "draft"
    revision: int = 0
    description: str | None = None
    applicant_party_id: str | None = None
    submitted_facts: dict[str, Any] = Field(default_factory=dict)
    scenario_id: str | None = None


class ApplicationPartyFixture(StrictModel):
    application_party_id: str
    application_id: str
    party_id: str
    party_role: str
    is_primary: bool = False
    authority_evidence_ref: str | None = None
    scenario_id: str | None = None


class ApplicationSiteFixture(StrictModel):
    application_site_id: str
    application_id: str
    parcel_id: str | None = None
    address_id: str | None = None
    is_primary: bool = True
    resolution_status: str = "unresolved"
    submitted_address_text: str | None = None
    scenario_id: str | None = None


class ApplicationRevisionFixture(StrictModel):
    revision_id: str
    application_id: str
    revision_number: int
    submitted_at: datetime
    submitted_by_actor_id: str | None = None
    snapshot: dict[str, Any] = Field(default_factory=dict)
    date_basis: str | None = None
    scenario_id: str | None = None


class PaymentFixture(StrictModel):
    payment_id: str
    source_transaction_id: str
    source_system_id: str = "erp_finance"
    source_event_id: str | None = None
    source_event_version: str | None = None
    payer_account_id: str | None = None
    party_id: str | None = None
    paid_at: datetime | None = None
    amount_cents: int = 0
    currency: str = "USD"
    settlement_status: str = "unsettled"
    scenario_id: str | None = None


class PaymentEventFixture(StrictModel):
    event_id: str
    payment_id: str
    source_event_id: str
    source_event_version: str | None = None
    event_type: str
    amount_cents: int = 0
    currency: str = "USD"
    occurred_at: datetime
    scenario_id: str | None = None


class DecisionFixture(StrictModel):
    decision_id: str
    application_id: str
    decision_type: str = "review"
    outcome: str
    decided_by_actor_id: str
    decided_at: datetime
    reason: str | None = None
    input_versions: dict[str, Any] = Field(default_factory=dict)
    rule_versions: dict[str, Any] = Field(default_factory=dict)
    status: str = "current"
    stale: bool = False
    scenario_id: str | None = None


class PermitFixture(StrictModel):
    permit_id: str
    application_id: str
    decision_id: str
    permit_number: str
    issued_at: datetime
    expires_at: datetime | None = None
    status: str = "issued"
    snapshot: dict[str, Any] = Field(default_factory=dict)
    artifact_hash: str
    issuance_command_key: str
    issued_by_actor_id: str | None = None
    fictional_demo: bool = True
    scenario_id: str | None = None


class AssessmentFixture(StrictModel):
    assessment_id: str
    application_id: str
    billed_party_id: str | None = None
    fee_schedule_version_id: str
    input_versions: dict[str, Any] = Field(default_factory=dict)
    assessed_total_cents: int = 0
    currency: str = "USD"
    status: str = "current"
    scenario_id: str | None = None


class AssessmentLineFixture(StrictModel):
    line_id: str
    assessment_id: str
    fee_code: str
    description: str
    quantity: str = "1"
    rate_cents: int = 0
    amount_cents: int = 0
    currency: str = "USD"
    rule_version_id: str | None = None


class AllocationFixture(StrictModel):
    allocation_id: str
    payment_id: str
    assessment_id: str
    assessment_line_id: str | None = None
    amount_cents: int = 0
    currency: str = "USD"
    status: str = "active"
    actor_id: str | None = None
    supersedes_allocation_id: str | None = None
    idempotency_key: str | None = None
    scenario_id: str | None = None


class BasePopulation(CatalogModel):
    fixture_version: str
    fictional_demo: bool = True
    parties: list[PartyFixture] = Field(default_factory=list)
    party_aliases: list[AliasFixture] = Field(default_factory=list)
    party_contacts: list[ContactFixture] = Field(default_factory=list)
    parcels: list[ParcelFixture] = Field(default_factory=list)
    addresses: list[AddressFixture] = Field(default_factory=list)
    parcel_addresses: list[ParcelAddressFixture] = Field(default_factory=list)
    credentials: list[CredentialFixture] = Field(default_factory=list)
    finance_accounts: list[FinanceAccountFixture] = Field(default_factory=list)
    applications: list[ApplicationFixture] = Field(default_factory=list)
    application_parties: list[ApplicationPartyFixture] = Field(default_factory=list)
    application_sites: list[ApplicationSiteFixture] = Field(default_factory=list)
    application_revisions: list[ApplicationRevisionFixture] = Field(default_factory=list)
    payments: list[PaymentFixture] = Field(default_factory=list)
    payment_events: list[PaymentEventFixture] = Field(default_factory=list)
    decisions: list[DecisionFixture] = Field(default_factory=list)
    permits: list[PermitFixture] = Field(default_factory=list)
    assessments: list[AssessmentFixture] = Field(default_factory=list)
    assessment_lines: list[AssessmentLineFixture] = Field(default_factory=list)
    allocations: list[AllocationFixture] = Field(default_factory=list)


class SourceVariationFixture(TimestampedModel):
    source_system_id: str
    source_dataset_id: str
    source_record_id: str
    source_record_version: str | None = None
    source_updated_at: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    ingested_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    record_status: str = "accepted"
    scenario_id: str | None = None


class SourceVariations(CatalogModel):
    fixture_version: str
    fictional_demo: bool = True
    source_variations: list[SourceVariationFixture] = Field(default_factory=list)


__all__ = [
    "ActorCatalog",
    "AddressFixture",
    "AliasFixture",
    "ApplicationFixture",
    "ApplicationPartyFixture",
    "ApplicationRevisionFixture",
    "ApplicationSiteFixture",
    "AssessmentFixture",
    "AssessmentLineFixture",
    "AllocationFixture",
    "BasePopulation",
    "ContactFixture",
    "ContractCatalog",
    "ContractFixture",
    "CredentialFixture",
    "DecisionFixture",
    "DemoConfig",
    "DomainCatalog",
    "DomainFixture",
    "FinanceAccountFixture",
    "GrantFixture",
    "PartyFixture",
    "ParcelAddressFixture",
    "ParcelFixture",
    "PaymentEventFixture",
    "PaymentFixture",
    "PermitFixture",
    "PermitTypeFixture",
    "PermissionCatalog",
    "PersonaFixture",
    "PermissionEntry",
    "PolicyCatalog",
    "PolicyFixture",
    "QueueFixture",
    "RoleFixture",
    "RuleCatalog",
    "RuleFixture",
    "ScenarioFixture",
    "ServiceIdentityFixture",
    "SourceVariationFixture",
    "SourceVariations",
]
