"""The deterministic demo reset.

The reset is destructive and deliberately narrow: it only accepts a database
that carries the fictional demonstration marker, and it only accepts the exact
confirmation phrase.  Every other target is refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from acme_city.core.clock import utc_now
from acme_city.core.errors import ValidationError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.persistence.base import Base
from acme_city.persistence.models import (  # noqa: F401  (registers every table on the metadata)
    agent,
    audit,
    change,
    finance,
    gis,
    governance,
    model_run,
    permit,
    registry,
    source,
)

ENVIRONMENT_ID = "local"


@dataclass(frozen=True)
class ResetResult:
    """What a reset produced."""

    fixture_version: str
    counts: dict[str, int]
    reset_at: datetime

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_version": self.fixture_version,
            "counts": dict(self.counts),
            "total": self.total,
        }


def _require_fictional_marker(session: Session) -> governance.DemoEnvironment:
    """Return the marker row, or refuse the reset."""
    marker = session.execute(
        select(governance.DemoEnvironment).where(
            governance.DemoEnvironment.environment_id == ENVIRONMENT_ID
        )
    ).scalar_one_or_none()
    if marker is None:
        raise ValidationError(
            "refusing to reset: the database is not marked as the fictional demonstration environment"
        )
    if not marker.fictional_demo:
        raise ValidationError(
            "refusing to reset: the database is explicitly not marked fictional_demo=true"
        )
    return marker


def _clear(session: Session) -> None:
    """Remove every business row, children before parents."""
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(delete(table))


def reset_demo(
    session: Session, bundle: FixtureBundle, *, confirmation: str
) -> ResetResult:
    """Reset the demonstration database to the declared fixture version.

    Args:
        session: An open session.  The reset runs inside the caller's
            transaction so that a failure leaves the database untouched.
        bundle: The validated fixture bundle.
        confirmation: The exact confirmation phrase.  Anything else is refused.

    Returns:
        A :class:`ResetResult` with the fixture version and the seeded counts.
    """
    expected = str(bundle.demo.reset.get("confirmation_phrase", ""))
    if confirmation != expected:
        raise ValidationError(
            "refusing to reset: the confirmation phrase does not match the configured phrase"
        )

    marker = _require_fictional_marker(session)
    marker_label = marker.label
    _clear(session)
    session.flush()
    # The marker row was deleted with everything else; detach the stale instance
    # so that the replacement row can be inserted cleanly.
    session.expunge_all()

    counts: dict[str, int] = {}
    epoch = bundle.demo.assignment_epoch
    policy_epoch = bundle.demo.policy_epoch

    # ----------------------------------------------------------- governance
    for role in bundle.actors.roles:
        session.add(
            governance.Role(
                id=f"role_{role.role_id}",
                role_id=role.role_id,
                label=role.label,
                boundary=role.boundary,
                active=True,
            )
        )
    counts["roles"] = len(bundle.actors.roles)
    session.flush()

    for entry in bundle.permissions.permissions:
        session.add(
            governance.Permission(
                id=f"permission_{entry.permission_id}",
                permission_id=entry.permission_id,
                action=entry.action,
                category=entry.category,
                description=entry.description,
                sensitive=entry.sensitive,
            )
        )
    counts["permissions"] = len(bundle.permissions.permissions)
    session.flush()

    role_permission_rows = 0
    for role in bundle.actors.roles:
        for permission_id in role.permission_ids:
            session.add(
                governance.RolePermission(
                    id=f"roleperm_{role.role_id}_{permission_id}",
                    role_id=role.role_id,
                    permission_id=permission_id,
                )
            )
            role_permission_rows += 1
    counts["role_permissions"] = role_permission_rows
    session.flush()

    for actor in bundle.all_actors:
        session.add(
            governance.Actor(
                id=actor.actor_id,
                actor_id=actor.actor_id,
                label=actor.label,
                active=actor.active_when_seeded,
                fictional=actor.fictional,
                selectable=bool(getattr(actor, "selectable", False)),
            )
        )
    counts["actors"] = len(bundle.all_actors)
    session.flush()

    actor_role_rows = 0
    for actor in bundle.all_actors:
        role_ids = getattr(actor, "source_role_ids", None) or getattr(actor, "role_ids", [])
        for role_id in role_ids:
            session.add(
                governance.ActorRole(
                    id=f"actorrole_{actor.actor_id}_{role_id}",
                    actor_id=actor.actor_id,
                    role_id=role_id,
                )
            )
            actor_role_rows += 1
    counts["actor_roles"] = actor_role_rows
    session.flush()

    grant_rows = 0
    for actor in bundle.all_actors:
        for grant in actor.grants:
            domains = grant.domains or [None]
            for domain_id in domains:
                session.add(
                    governance.ActorGrant(
                        id=f"grant_{actor.actor_id}_{grant.permission_id}_{domain_id or 'all'}",
                        actor_id=actor.actor_id,
                        permission_id=grant.permission_id,
                        domain_id=domain_id,
                        record_scope=list(grant.record_scope),
                        effective_from=epoch,
                        effective_to=None,
                        granted_by_actor_id="persona_city_administrator",
                        reason="fictional demonstration seed grant",
                        source=grant.source,
                    )
                )
                grant_rows += 1
    counts["actor_grants"] = grant_rows
    session.flush()

    for domain in bundle.domains.domains:
        session.add(
            governance.Domain(
                id=f"domain_{domain.domain_id}",
                domain_id=domain.domain_id,
                label=domain.label,
                accountable_owner_actor_id=domain.accountable_owner_actor_id,
                steward_queue_id=domain.steward_queue_id,
                system_custodian_actor_id=domain.system_custodian_actor_id,
                default_source_system_id=domain.default_source_system_id,
                default_dataset_key=domain.default_dataset_key,
                owner_strategy=domain.owner_strategy,
                active=True,
            )
        )
    counts["domains"] = len(bundle.domains.domains)
    session.flush()

    for queue in bundle.domains.steward_queues:
        target = queue.first_review_target
        session.add(
            governance.StewardQueue(
                id=f"queue_{queue.queue_id}",
                queue_id=queue.queue_id,
                domain_id=queue.domain_id,
                label=queue.domain_id.replace("_", " ").title(),
                primary_actor_id=queue.primary_actor_id,
                delegate_actor_id=queue.delegate_actor_id,
                escalation_actor_id=queue.escalation_actor_id,
                cross_domain_escalation_actor_id=queue.cross_domain_escalation_actor_id,
                first_review_target_quantity=int(target.get("quantity", 1)),
                first_review_target_unit=str(target.get("unit", "business_day")),
                first_review_target_calendar_basis=str(
                    target.get("calendar_basis", "configured_demo_calendar")
                ),
                configurable=bool(target.get("configurable", True)),
                service_promise=bool(target.get("service_promise", False)),
                active=True,
            )
        )
    counts["steward_queues"] = len(bundle.domains.steward_queues)
    session.flush()

    assignment_rows = 0
    for domain in bundle.domains.domains:
        queue = next(
            (q for q in bundle.domains.steward_queues if q.queue_id == domain.steward_queue_id),
            None,
        )
        bindings: list[tuple[str, str | None, str | None]] = [
            ("owner", domain.accountable_owner_actor_id, None),
            ("custodian", domain.system_custodian_actor_id, None),
        ]
        if queue is not None:
            bindings.extend(
                [
                    ("steward", queue.primary_actor_id, queue.queue_id),
                    ("delegate", queue.delegate_actor_id, queue.queue_id),
                    ("escalation", queue.escalation_actor_id, queue.queue_id),
                ]
            )
        for responsibility, actor_id, queue_id in bindings:
            if not actor_id:
                continue
            session.add(
                governance.Assignment(
                    id=f"assign_{domain.domain_id}_{responsibility}",
                    subject_type="domain",
                    subject_id=domain.domain_id,
                    responsibility=responsibility,
                    actor_id=actor_id,
                    queue_id=queue_id,
                    effective_from=epoch,
                    effective_to=None,
                    reason="fictional demonstration seed assignment",
                    source="seed_config",
                )
            )
            assignment_rows += 1
    counts["assignments"] = assignment_rows

    for contract in bundle.contracts.source_contracts:
        session.add(
            governance.SourceContract(
                id=contract.contract_id,
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
                business_key_fields=list(contract.business_key_fields),
                schema_version=contract.schema_version,
                required_fields=dict(contract.required_fields),
                allowed_values=dict(contract.allowed_values),
                date_meanings=dict(contract.date_meanings),
                field_classes=dict(contract.field_classes),
                registration_state=contract.registration_state,
                registered_at=epoch,
            )
        )
    counts["source_contracts"] = len(bundle.contracts.source_contracts)

    for policy in bundle.policies.authority_policies:
        session.add(
            governance.AuthorityPolicy(
                id=f"authpol_{policy.policy_id}",
                policy_id=policy.policy_id,
                field_group=policy.field_group,
                domain_id=policy.domain_id,
                authoritative_source_system_id=policy.authoritative_source_system_id,
                authoritative_component_id=policy.authoritative_component_id,
                authoritative_dataset_key=policy.authoritative_dataset_key,
                change_destination=policy.change_destination,
                user_action=policy.user_action,
                requires_source_ack=policy.requires_source_ack_for_factual_correction,
                decision_relevant=policy.decision_relevant_by_default,
                status=policy.status,
                effective_from=policy.effective_from or policy_epoch,
                effective_to=policy.effective_to,
                approver_actor_id=policy.approver_actor_id,
                authoritative_action_roles=list(policy.authoritative_action_actor_roles),
                published_at=None,
            )
        )
    counts["authority_policies"] = len(bundle.policies.authority_policies)

    # ----------------------------------------------------------- source intake
    systems = [
        ("permitting", "Permitting", True, True),
        ("gis", "GIS", True, True),
        ("erp_finance", "ERP/Finance", True, True),
        ("intake_portal", "ACME ePermit Portal (simulated)", True, True),
        ("registry", "Registry and governed application components", False, False),
    ]
    for source_system_id, label, simulated, incoming in systems:
        session.add(
            source.SourceSystem(
                id=f"srcsys_{source_system_id}",
                source_system_id=source_system_id,
                label=label,
                simulated=simulated,
                incoming=incoming,
                description="fictional demonstration source" if incoming else "application component",
            )
        )
    counts["source_systems"] = len(systems)
    session.flush()

    # ----------------------------------------------------------- catalogue
    for permit_type in bundle.rules.permit_types:
        session.add(
            permit.PermitType(
                id=permit_type.permit_type_id,
                permit_type_id=permit_type.permit_type_id,
                key=permit_type.key,
                label=permit_type.label,
                review_route=permit_type.review_route,
                required_fields=list(permit_type.required_fields),
                required_documents=list(permit_type.required_documents),
                active=True,
                review_area=permit_type.review_area,
                process_category=permit_type.process_category,
                discretionary=bool(permit_type.discretionary),
                description=permit_type.description or None,
                fee_schedule_key=permit_type.fee_schedule_key,
            )
        )
    counts["permit_types"] = len(bundle.rules.permit_types)
    session.flush()

    # --------------------------------------------------------- agent controls
    # Both agents sleep after a reset.  Nothing runs until a City
    # Administrator wakes one and a person asks it to run.
    for agent_key in ("intake", "adjudication"):
        session.add(
            agent.AgentControl(
                id=f"agentctl_{agent_key}",
                correlation_id=f"corr_reset_{agent_key}",
                agent_key=agent_key,
                mode=agent.AGENT_ASLEEP,
                version=1,
                changed_by=None,
                changed_at=None,
            )
        )
    counts["agent_controls"] = 2

    # ----------------------------------------------------------- reason codes
    for reason_code in bundle.demo.reason_codes:
        session.add(
            permit.ReasonCode(
                id=f"reasoncode_{reason_code.code.lower()}",
                correlation_id=f"corr_reason_{reason_code.code.lower()}",
                code=reason_code.code,
                label=reason_code.label,
                description=reason_code.description or None,
                code_type=reason_code.code_type,
                active=True,
                version=1,
                changed_by=None,
                changed_at=None,
            )
        )
    counts["reason_codes"] = len(bundle.demo.reason_codes)
    session.flush()

    rule_id_by_key: dict[tuple[str, int], str] = {}
    for rule in bundle.rules.rules:
        row_id = f"rulever_{rule.rule_id}_v{rule.version}"
        rule_id_by_key[(rule.rule_id, rule.version)] = row_id
        permit_type_id = next(
            (
                permit_type.permit_type_id
                for permit_type in bundle.rules.permit_types
                if permit_type.key == rule.permit_type
            ),
            None,
        )
        session.add(
            finance.RuleVersion(
                id=row_id,
                rule_id=rule.rule_id,
                permit_type_id=permit_type_id,
                kind=rule.kind,
                title=rule.title,
                citation=rule.citation,
                field_path=rule.field_path,
                operator=rule.operator,
                limit_value=rule.limit_value,
                on_violate=rule.on_violate,
                condition=dict(rule.condition) if rule.condition else None,
                message=rule.message,
                condition_note=rule.condition_note,
                effective_from=rule.effective_from or policy_epoch,
                effective_to=rule.effective_to,
                status=rule.status,
                approver_actor_id=rule.approver_actor_id,
                author_actor_id=rule.author_actor_id,
                source_mapping=dict(rule.source_mapping),
            )
        )
    counts["rule_versions"] = len(bundle.rules.rules)
    session.flush()

    fee_schedule_ids: dict[str, str] = {}
    for schedule in bundle.rules.fee_schedules:
        row_id = f"feesched_{schedule.fee_schedule_id}_{schedule.version_label.replace('.', '_')}"
        fee_schedule_ids[f"{schedule.fee_schedule_id}:{schedule.version_label}"] = row_id
        session.add(
            finance.FeeScheduleVersion(
                id=row_id,
                fee_schedule_id=schedule.fee_schedule_id,
                version_label=schedule.version_label,
                effective_from=schedule.effective_from or policy_epoch,
                effective_to=schedule.effective_to,
                currency=schedule.currency,
                definition=dict(schedule.definition),
                approver_actor_id=schedule.approver_actor_id,
                author_actor_id=schedule.author_actor_id,
                status=schedule.status,
            )
        )
    counts["fee_schedule_versions"] = len(bundle.rules.fee_schedules)
    session.flush()

    # ----------------------------------------------------------- registry
    population = bundle.base_population
    for party in population.parties:
        session.add(
            registry.CanonicalEntity(
                id=f"entity_{party.party_id}",
                entity_id=party.party_id,
                entity_type="party",
                label=party.display_name,
                status="active",
            )
        )
    session.flush()

    for party in population.parties:
        session.add(
            registry.Party(
                id=party.party_id,
                entity_id=party.party_id,
                party_type=party.party_type,
                display_name=party.display_name,
                legal_name=party.legal_name,
                status=party.status,
            )
        )
    counts["parties"] = len(population.parties)
    session.flush()

    for alias in population.party_aliases:
        session.add(
            registry.PartyAlias(
                id=alias.alias_id,
                party_id=alias.party_id,
                alias_value=alias.alias_value,
                alias_type=alias.alias_type,
                source_snapshot_id=None,
                recorded_at=bundle.demo.assignment_epoch,
            )
        )
    counts["party_aliases"] = len(population.party_aliases)

    for contact in population.party_contacts:
        session.add(
            registry.PartyContact(
                id=contact.contact_id,
                party_id=contact.party_id,
                contact_type=contact.contact_type,
                value=contact.value,
                verification_state=contact.verification_state,
                source_snapshot_id=None,
                valid_from=contact.valid_from,
                valid_to=contact.valid_to,
            )
        )
    counts["party_contacts"] = len(population.party_contacts)
    session.flush()

    for parcel in population.parcels:
        session.add(
            registry.Parcel(
                id=parcel.parcel_id,
                parcel_id=parcel.parcel_id,
                jurisdiction_id=parcel.jurisdiction_id,
                source_parcel_number=parcel.source_parcel_number,
                status=parcel.status,
                valid_from=parcel.valid_from,
                valid_to=parcel.valid_to,
                source_snapshot_id=None,
            )
        )
    counts["parcels"] = len(population.parcels)

    for address in population.addresses:
        session.add(
            registry.Address(
                id=address.address_id,
                address_id=address.address_id,
                street_number=address.street_number,
                street_name=address.street_name,
                street_type=address.street_type,
                unit_type=address.unit_type,
                unit_number=address.unit_number,
                municipality=address.municipality,
                region=address.region,
                postcode=address.postcode,
                source_string=address.source_string,
                status=address.status,
                source_snapshot_id=None,
            )
        )
    counts["addresses"] = len(population.addresses)
    session.flush()

    for relation in population.parcel_addresses:
        session.add(
            registry.ParcelAddress(
                id=relation.relationship_id,
                parcel_id=relation.parcel_id,
                address_id=relation.address_id,
                relationship_type=relation.relationship_type,
                effective_from=relation.effective_from,
                effective_to=relation.effective_to,
                evidence_ref=relation.evidence_ref,
            )
        )
    counts["parcel_addresses"] = len(population.parcel_addresses)
    session.flush()

    # The synthetic town: attributes on the base parcels and addresses, the rest
    # of the town, the street layer, the zoning register and the simulated
    # subscriber departments.
    from acme_city.gis.seed import seed_gis

    seed_gis(session, bundle.root, bundle.demo.assignment_epoch)

    for credential in population.credentials:
        session.add(
            registry.Credential(
                id=credential.credential_id,
                credential_id=credential.credential_id,
                holder_party_id=credential.holder_party_id,
                credential_type=credential.credential_type,
                issuing_authority_id=credential.issuing_authority_id,
                number=credential.number,
                status=credential.status,
                valid_from=credential.valid_from,
                valid_to=credential.valid_to,
                verified_at=credential.verified_at,
                source_system_id=credential.source_system_id,
                source_record_id=credential.source_record_id,
                source_snapshot_id=None,
                scenario_id=credential.scenario_id,
            )
        )
    counts["credentials"] = len(population.credentials)

    for account in population.finance_accounts:
        session.add(
            registry.FinanceAccount(
                id=account.account_id,
                account_id=account.account_id,
                source_account_id=account.source_account_id,
                source_system_id=account.source_system_id,
                party_id=account.party_id,
                account_role=account.account_role,
                source_version=account.source_version,
                link_status=account.link_status,
                link_decision=account.link_decision,
                scenario_id=account.scenario_id,
            )
        )
    counts["finance_accounts"] = len(population.finance_accounts)
    session.flush()

    # ----------------------------------------------------------- applications
    permit_type_id_by_key = {
        permit_type.key: permit_type.permit_type_id for permit_type in bundle.rules.permit_types
    }
    for application in population.applications:
        session.add(
            permit.Application(
                id=application.application_id,
                source_application_number=application.source_application_number,
                permit_type_id=permit_type_id_by_key[application.permit_type],
                initial_submitted_at=application.initial_submitted_at,
                revision_submitted_at=application.revision_submitted_at,
                status=application.status,
                revision=application.revision,
                description=application.description,
                submitted_facts=dict(application.submitted_facts),
                applicant_party_id=application.applicant_party_id,
                correlation_id=f"corr_seed_{application.application_id}",
                scenario_id=application.scenario_id,
            )
        )
    counts["applications"] = len(population.applications)
    session.flush()

    for member in population.application_parties:
        session.add(
            permit.ApplicationParty(
                id=member.application_party_id,
                application_id=member.application_id,
                party_id=member.party_id,
                party_role=member.party_role,
                is_primary=member.is_primary,
                authority_evidence_ref=member.authority_evidence_ref,
            )
        )
    counts["application_parties"] = len(population.application_parties)

    for site in population.application_sites:
        session.add(
            permit.ApplicationSite(
                id=site.application_site_id,
                application_id=site.application_id,
                parcel_id=site.parcel_id,
                address_id=site.address_id,
                is_primary=site.is_primary,
                resolution_status=site.resolution_status,
                submitted_address_text=site.submitted_address_text,
            )
        )
    counts["application_sites"] = len(population.application_sites)

    for revision in population.application_revisions:
        session.add(
            permit.ApplicationRevision(
                id=revision.revision_id,
                application_id=revision.application_id,
                revision_number=revision.revision_number,
                submitted_at=revision.submitted_at,
                submitted_by_actor_id=revision.submitted_by_actor_id,
                snapshot=dict(revision.snapshot),
                date_basis=revision.date_basis,
            )
        )
    counts["application_revisions"] = len(population.application_revisions)
    session.flush()

    # ----------------------------------------------------------- finance
    for payment in population.payments:
        session.add(
            finance.Payment(
                id=payment.payment_id,
                source_transaction_id=payment.source_transaction_id,
                source_system_id=payment.source_system_id,
                source_event_id=payment.source_event_id,
                source_event_version=payment.source_event_version,
                payer_account_id=payment.payer_account_id,
                party_id=payment.party_id,
                paid_at=payment.paid_at,
                amount_cents=payment.amount_cents,
                currency=payment.currency,
                settlement_status=payment.settlement_status,
                scenario_id=payment.scenario_id,
            )
        )
    counts["payments"] = len(population.payments)
    session.flush()

    for event in population.payment_events:
        session.add(
            finance.PaymentEvent(
                id=event.event_id,
                payment_id=event.payment_id,
                source_event_id=event.source_event_id,
                source_event_version=event.source_event_version,
                event_type=event.event_type,
                amount_cents=event.amount_cents,
                currency=event.currency,
                occurred_at=event.occurred_at,
            )
        )
    counts["payment_events"] = len(population.payment_events)

    for assessment in population.assessments:
        session.add(
            finance.Assessment(
                id=assessment.assessment_id,
                application_id=assessment.application_id,
                billed_party_id=assessment.billed_party_id,
                fee_schedule_version_id=fee_schedule_ids[assessment.fee_schedule_version_id],
                input_versions=dict(assessment.input_versions),
                correlation_id=f"corr_seed_{assessment.assessment_id}",
                assessed_total_cents=assessment.assessed_total_cents,
                currency=assessment.currency,
                status=assessment.status,
                scenario_id=assessment.scenario_id,
            )
        )
    counts["assessments"] = len(population.assessments)
    session.flush()

    for line in population.assessment_lines:
        session.add(
            finance.AssessmentLine(
                id=line.line_id,
                assessment_id=line.assessment_id,
                fee_code=line.fee_code,
                description=line.description,
                quantity=line.quantity,
                rate_cents=line.rate_cents,
                amount_cents=line.amount_cents,
                currency=line.currency,
                rule_version_id=line.rule_version_id,
            )
        )
    counts["assessment_lines"] = len(population.assessment_lines)
    session.flush()

    for allocation in population.allocations:
        session.add(
            finance.Allocation(
                id=allocation.allocation_id,
                payment_id=allocation.payment_id,
                assessment_id=allocation.assessment_id,
                assessment_line_id=allocation.assessment_line_id,
                amount_cents=allocation.amount_cents,
                currency=allocation.currency,
                status=allocation.status,
                actor_id=allocation.actor_id,
                supersedes_allocation_id=allocation.supersedes_allocation_id,
                idempotency_key=allocation.idempotency_key,
                scenario_id=allocation.scenario_id,
            )
        )
    counts["allocations"] = len(population.allocations)

    for decision in population.decisions:
        session.add(
            permit.Decision(
                id=decision.decision_id,
                application_id=decision.application_id,
                decision_type=decision.decision_type,
                outcome=decision.outcome,
                decided_by_actor_id=decision.decided_by_actor_id,
                decided_at=decision.decided_at,
                reason=decision.reason,
                input_versions=dict(decision.input_versions),
                rule_versions=dict(decision.rule_versions),
                status=decision.status,
                stale=decision.stale,
                scenario_id=decision.scenario_id,
            )
        )
    counts["decisions"] = len(population.decisions)
    session.flush()

    for permit_row in population.permits:
        session.add(
            permit.Permit(
                id=permit_row.permit_id,
                application_id=permit_row.application_id,
                decision_id=permit_row.decision_id,
                permit_number=permit_row.permit_number,
                issued_at=permit_row.issued_at,
                expires_at=permit_row.expires_at,
                status=permit_row.status,
                snapshot=dict(permit_row.snapshot),
                artifact_hash=permit_row.artifact_hash,
                issuance_command_key=permit_row.issuance_command_key,
                issued_by_actor_id=permit_row.issued_by_actor_id,
                fictional_demo=True,
            )
        )
    counts["permits"] = len(population.permits)

    # ----------------------------------------------------------- source snapshots
    snapshot_rows = bundle.source_snapshot_rows()
    for row in snapshot_rows:
        session.add(
            source.SourceSnapshot(
                source_snapshot_id=row["source_snapshot_id"],
                correlation_id=row["correlation_id"],
                ingestion_run_id=None,
                source_system_id=row["source_system_id"],
                source_dataset_id=row["source_dataset_id"],
                source_record_id=row["source_record_id"],
                source_record_version=row["source_record_version"],
                source_updated_at=row["source_updated_at"],
                effective_from=row["effective_from"],
                effective_to=row["effective_to"],
                ingested_at=row["ingested_at"],
                payload_hash=row["payload_hash"],
                raw_payload=row["raw_payload"],
                record_status=row["record_status"],
                scenario_id=row["scenario_id"],
            )
        )
    counts["source_snapshots"] = len(snapshot_rows)

    # ----------------------------------------------------------- marker
    session.add(
        governance.DemoEnvironment(
            id=marker.id,
            environment_id=ENVIRONMENT_ID,
            fictional_demo=True,
            fixture_version=bundle.fixture_version,
            label=marker_label,
            updated_at=utc_now(),
        )
    )
    counts["demo_environment"] = 1

    # Bundled permit-type icons are part of the seeded population, so no
    # page view has to create them later.
    from acme_city.permits.icons import ensure_seeded

    ensure_seeded(session)
    counts["permit_type_icons"] = session.execute(
        select(func.count()).select_from(permit.PermitTypeIcon)
    ).scalar_one()

    session.flush()
    return ResetResult(
        fixture_version=bundle.fixture_version, counts=counts, reset_at=utc_now()
    )


def seeded_row_counts(session: Session) -> dict[str, int]:
    """Return the row count of every business table, for verification."""
    counts: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        if table.name == "alembic_version":
            continue
        counts[table.name] = session.execute(
            select(func.count()).select_from(table)
        ).scalar_one()
    return counts


__all__ = ["ENVIRONMENT_ID", "ResetResult", "reset_demo", "seeded_row_counts"]
