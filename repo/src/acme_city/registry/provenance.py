"""Field-level provenance and the trusted view.

The trusted view does not show the newest value or the value with the highest
proposal score.  It shows the value that the published authority policy names,
and it keeps the disagreement with every other source visible.
"""
# REQUIRES: MDM-04, GOV-05, CHG-03, CHG-04
# The trusted view is built from the declared authority policy, the field-level
# provenance is recorded for every chosen value, and an unknown or disputed
# authority creates an assigned issue and a dependent blocker.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.core.clock import utc_now
from acme_city.core.ids import new_id
from acme_city.persistence.models import change, finance, governance, permit, registry, source


@dataclass(frozen=True)
class AttributeRule:
    """One displayed attribute and the authority that owns it."""

    attribute_path: str
    policy_id: str
    source_fields: tuple[str, ...]
    label: str = ""


#: The attributes the trusted view shows for each entity family, with the
#: authority policy that owns them.
ENTITY_ATTRIBUTES: dict[str, tuple[AttributeRule, ...]] = {
    "party": (
        AttributeRule(
            "display_name",
            "authority_person_identity",
            ("display_name", "organization_name"),
            "Recorded name",
        ),
        AttributeRule(
            "contact_email",
            "authority_applicant_contact",
            ("contact_email",),
            "Contact email",
        ),
        AttributeRule(
            "contact_phone",
            "authority_applicant_contact",
            ("contact_phone",),
            "Contact telephone",
        ),
        AttributeRule(
            "preferred_contact",
            "authority_applicant_contact",
            ("preferred_contact",),
            "Preferred contact method",
        ),
        AttributeRule(
            "business_license_status",
            "authority_business_identity",
            ("status",),
            "Business license status",
        ),
        AttributeRule(
            "business_license_number",
            "authority_business_identity",
            ("license_number",),
            "Business license number",
        ),
        AttributeRule(
            "contractor_registration_status",
            "authority_contractor",
            ("status",),
            "Contractor registration status",
        ),
        AttributeRule(
            "finance_account_id",
            "authority_accounts",
            ("source_account_id",),
            "Finance account",
        ),
        AttributeRule(
            "finance_account_role",
            "authority_accounts",
            ("account_role",),
            "Finance account role",
        ),
    ),
    "parcel": (
        AttributeRule("parcel_number", "authority_parcel", ("parcel_number",), "Parcel number"),
        AttributeRule("parcel_status", "authority_parcel", ("status",), "Parcel status"),
    ),
    "address": (
        AttributeRule("source_string", "authority_address", ("source_string",), "Address"),
        AttributeRule("unit_type", "authority_address", ("unit_type",), "Unit type"),
        AttributeRule("unit_number", "authority_address", ("unit_number",), "Unit number"),
    ),
}


def policy_for(session: Session, policy_id: str) -> governance.AuthorityPolicy | None:
    """Return the authority policy with an identifier."""
    return session.execute(
        select(governance.AuthorityPolicy).where(
            governance.AuthorityPolicy.policy_id == policy_id
        )
    ).scalar_one_or_none()


def current_accepted_snapshot(
    session: Session, source_system_id: str, dataset_key: str, record_id: str
) -> source.SourceSnapshot | None:
    """Return the accepted snapshot of a source record with the newest version."""
    rows = session.execute(
        select(source.SourceSnapshot).where(
            source.SourceSnapshot.source_system_id == source_system_id,
            source.SourceSnapshot.source_dataset_id == dataset_key,
            source.SourceSnapshot.source_record_id == record_id,
            source.SourceSnapshot.record_status == "accepted",
        )
    ).scalars().all()
    if not rows:
        return None

    def sort_key(row: source.SourceSnapshot) -> tuple[int, int, datetime]:
        numeric = row.source_record_version or ""
        return (
            int(numeric) if numeric.isdigit() else -1,
            1 if row.source_updated_at is not None else 0,
            row.source_updated_at or row.ingested_at,
        )

    return max(rows, key=sort_key)


def _crosswalk_view(row: registry.Crosswalk) -> dict[str, Any]:
    """Return the dictionary form of one crosswalk."""
    return {
        "crosswalk_id": row.id,
        "entity_id": row.entity_id,
        "entity_type": row.entity_type,
        "source_system_id": row.source_system_id,
        "source_dataset_key": row.source_dataset_key,
        "source_record_id": row.source_record_id,
        "link_status": row.link_status,
        "decision": row.decision,
        "decision_actor_id": row.decision_actor_id,
        "decided_at": row.decided_at,
        "expected_version": row.expected_version,
        "valid_from": row.valid_from,
        "valid_to": row.valid_to,
        "superseded_by_crosswalk_id": row.superseded_by_crosswalk_id,
        "version": row.version,
        "scenario_id": row.scenario_id,
    }


def crosswalk_view(row: registry.Crosswalk) -> Any:
    """Return the view model of one crosswalk."""
    from acme_city.registry.schemas import CrosswalkView

    return CrosswalkView(
        crosswalk_id=row.id,
        entity_id=row.entity_id,
        entity_type=row.entity_type,
        source_system_id=row.source_system_id,
        source_dataset_key=row.source_dataset_key,
        source_record_id=row.source_record_id,
        link_status=row.link_status,
        decision=row.decision,
        decision_actor_id=row.decision_actor_id,
        decided_at=row.decided_at,
        expected_version=row.expected_version,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        superseded_by_crosswalk_id=row.superseded_by_crosswalk_id,
        version=row.version,
        scenario_id=row.scenario_id,
    )


def _record_provenance(
    session: Session,
    *,
    entity_id: str,
    attribute_path: str,
    snapshot: source.SourceSnapshot,
    source_field: str,
    policy_id: str,
    reason: str,
    now: datetime,
) -> None:
    """Record the provenance of one chosen value, once."""
    existing = session.execute(
        select(registry.Provenance).where(
            registry.Provenance.entity_id == entity_id,
            registry.Provenance.attribute_path == attribute_path,
            registry.Provenance.source_snapshot_id == snapshot.source_snapshot_id,
        )
    ).scalars().first()
    if existing is not None:
        return
    session.add(
        registry.Provenance(
            id=new_id("prov"),
            entity_id=entity_id,
            attribute_path=attribute_path,
            source_snapshot_id=snapshot.source_snapshot_id,
            source_field=source_field,
            authority_policy_id=policy_id,
            reason=reason,
            valid_from=now,
            valid_to=None,
        )
    )


def _raise_authority_issue(
    session: Session,
    *,
    entity_id: str,
    attribute_path: str,
    policy_id: str,
    domain_id: str | None,
    now: datetime,
) -> str:
    """Create the assigned issue and dependent blocker of an unresolved authority."""
    queue = None
    if domain_id:
        queue = session.execute(
            select(governance.StewardQueue).where(
                governance.StewardQueue.domain_id == domain_id
            )
        ).scalars().first()
    assignee = queue.primary_actor_id if queue is not None else None
    subject_id = f"{entity_id}:{attribute_path}"
    existing = session.execute(
        select(change.GovernanceIssue).where(
            change.GovernanceIssue.subject_type == "canonical_entity",
            change.GovernanceIssue.subject_id == subject_id,
            change.GovernanceIssue.issue_type == "unresolved_field_authority",
            change.GovernanceIssue.status == "open",
        )
    ).scalars().first()
    if existing is not None:
        return existing.id
    issue = change.GovernanceIssue(
        id=new_id("issue"),
        subject_type="canonical_entity",
        subject_id=subject_id,
        issue_type="unresolved_field_authority",
        description=(
            f"the authority of {attribute_path!r} for {entity_id!r} is unknown: policy "
            f"{policy_id!r} names a source that has no approved link, so the displayed "
            "value has no declared owner"
        ),
        responsible_queue_id=queue.queue_id if queue is not None else None,
        assigned_actor_id=assignee,
        blocking=True,
        status="open",
        scenario_id=None,
    )
    session.add(issue)
    session.flush()

    deduplication_key = f"field_authority:{entity_id}:{attribute_path}"
    task = session.execute(
        select(change.ReviewTask).where(
            change.ReviewTask.deduplication_key == deduplication_key
        )
    ).scalars().first()
    if task is None:
        session.add(
            change.ReviewTask(
                id=new_id("task"),
                change_case_id=None,
                assignee_actor_id=assignee,
                task_type="field_authority",
                target_type="canonical_entity",
                target_id=entity_id,
                deduplication_key=deduplication_key,
                status="open",
                due_at=None,
                scenario_id=None,
            )
        )
        session.flush()
    return issue.id


def build_trusted_view(
    session: Session, entity_id: str, *, now: datetime | None = None
) -> Any:
    """Build the trusted view of one canonical entity.

    The view chooses the declared authoritative source for every attribute.  A
    newer record from another source, or a higher proposal score, does not
    change the choice.
    """
    from acme_city.registry.schemas import TrustedFieldView, TrustedView

    moment = now or utc_now()
    entity = session.execute(
        select(registry.CanonicalEntity).where(
            registry.CanonicalEntity.entity_id == entity_id
        )
    ).scalar_one_or_none()
    if entity is None:
        return None

    rows = session.execute(
        select(registry.Crosswalk)
        .where(registry.Crosswalk.entity_id == entity_id)
        .order_by(registry.Crosswalk.created_at, registry.Crosswalk.id)
    ).scalars().all()
    approved = [row for row in rows if row.link_status == "approved"]

    rules = ENTITY_ATTRIBUTES.get(entity.entity_type, ())
    fields: list[TrustedFieldView] = []
    disagreements: list[TrustedFieldView] = []
    issues: list[dict[str, Any]] = []

    for rule in rules:
        policy = policy_for(session, rule.policy_id)
        authoritative_snapshot = None
        authoritative_field = None
        if policy is not None and policy.authoritative_source_system_id:
            for row in approved:
                if row.source_system_id != policy.authoritative_source_system_id:
                    continue
                if (
                    policy.authoritative_dataset_key
                    and row.source_dataset_key
                    and row.source_dataset_key != policy.authoritative_dataset_key
                ):
                    continue
                snapshot = current_accepted_snapshot(
                    session,
                    row.source_system_id,
                    row.source_dataset_key or "",
                    row.source_record_id,
                )
                if snapshot is None or not snapshot.raw_payload:
                    continue
                for source_field in rule.source_fields:
                    if source_field in snapshot.raw_payload:
                        authoritative_snapshot = snapshot
                        authoritative_field = source_field
                        break
                if authoritative_snapshot is not None:
                    break

        other_values: list[TrustedFieldView] = []
        for row in approved:
            if authoritative_snapshot is not None and (
                row.source_system_id == authoritative_snapshot.source_system_id
                and row.source_record_id == authoritative_snapshot.source_record_id
            ):
                continue
            snapshot = current_accepted_snapshot(
                session, row.source_system_id, row.source_dataset_key or "", row.source_record_id
            )
            if snapshot is None or not snapshot.raw_payload:
                continue
            for source_field in rule.source_fields:
                if source_field not in snapshot.raw_payload:
                    continue
                other_values.append(
                    TrustedFieldView(
                        attribute_path=rule.attribute_path,
                        value=snapshot.raw_payload.get(source_field),
                        raw_value=snapshot.raw_payload.get(source_field),
                        source_system_id=row.source_system_id,
                        source_dataset_key=row.source_dataset_key,
                        source_record_id=row.source_record_id,
                        source_snapshot_id=snapshot.source_snapshot_id,
                        authority_policy_id=None,
                        state="disagreement",
                        reasons=[
                            f"the value is not owned by {rule.policy_id!r}; it is preserved "
                            "and marked as a disagreement"
                        ],
                    )
                )
                break

        if authoritative_snapshot is not None and authoritative_field is not None:
            value = authoritative_snapshot.raw_payload.get(authoritative_field)
            reasons = [
                f"{rule.policy_id!r} names {authoritative_snapshot.source_system_id} as the "
                f"owner of {rule.attribute_path!r}"
            ]
            fields.append(
                TrustedFieldView(
                    attribute_path=rule.attribute_path,
                    value=value,
                    raw_value=value,
                    source_system_id=authoritative_snapshot.source_system_id,
                    source_dataset_key=authoritative_snapshot.source_dataset_id,
                    source_record_id=authoritative_snapshot.source_record_id,
                    source_snapshot_id=authoritative_snapshot.source_snapshot_id,
                    authority_policy_id=rule.policy_id,
                    state="authoritative",
                    reasons=reasons,
                )
            )
            _record_provenance(
                session,
                entity_id=entity_id,
                attribute_path=rule.attribute_path,
                snapshot=authoritative_snapshot,
                source_field=authoritative_field,
                policy_id=rule.policy_id,
                reason=reasons[0],
                now=moment,
            )
            disagreements.extend(other_values)
            continue

        if other_values:
            issue_id = _raise_authority_issue(
                session,
                entity_id=entity_id,
                attribute_path=rule.attribute_path,
                policy_id=rule.policy_id,
                domain_id=policy.domain_id if policy is not None else None,
                now=moment,
            )
            issues.append(
                {
                    "issue_id": issue_id,
                    "attribute_path": rule.attribute_path,
                    "issue_type": "unresolved_field_authority",
                    "blocking": True,
                }
            )
            fields.append(
                TrustedFieldView(
                    attribute_path=rule.attribute_path,
                    value=None,
                    raw_value=None,
                    source_system_id=None,
                    source_dataset_key=None,
                    source_record_id=None,
                    source_snapshot_id=None,
                    authority_policy_id=rule.policy_id,
                    state="disputed",
                    reasons=[
                        f"{rule.policy_id!r} names a source that has no approved link, so the "
                        "value has no declared owner"
                    ],
                )
            )
            disagreements.extend(other_values)
            continue

        fields.append(
            TrustedFieldView(
                attribute_path=rule.attribute_path,
                value=None,
                raw_value=None,
                source_system_id=None,
                source_dataset_key=None,
                source_record_id=None,
                source_snapshot_id=None,
                authority_policy_id=rule.policy_id,
                state="absent",
                reasons=[f"no approved source provides {rule.attribute_path!r}"],
            )
        )

    session.flush()
    return TrustedView(
        entity_id=entity_id,
        entity_type=entity.entity_type,
        label=entity.label,
        fields=fields,
        disagreements=disagreements,
        issues=issues,
        crosswalks=[crosswalk_view(row) for row in rows],
        generated_at=moment,
    )


def affected_dependents(
    session: Session,
    *,
    entity_ids: tuple[str, ...] = (),
    application_ids: tuple[str, ...] = (),
) -> dict[str, list[str]]:
    """Return the records that depend on the given entities or applications.

    The result covers applications, evaluations, assessments, decisions and
    permits, so an impact preview can name every affected record before a
    change is approved.
    """
    applications: set[str] = set(application_ids)
    for entity_id in entity_ids:
        rows = session.execute(
            select(permit.Application.id).where(
                permit.Application.applicant_party_id == entity_id
            )
        ).all()
        applications.update(str(row[0]) for row in rows)
        rows = session.execute(
            select(permit.ApplicationParty.application_id).where(
                permit.ApplicationParty.party_id == entity_id
            )
        ).all()
        applications.update(str(row[0]) for row in rows)

    ordered = sorted(applications)
    evaluations: list[str] = []
    assessments: list[str] = []
    decisions: list[str] = []
    permits: list[str] = []
    if ordered:
        evaluations = [
            str(row[0])
            for row in session.execute(
                select(permit.Evaluation.id).where(
                    permit.Evaluation.application_id.in_(ordered)
                )
            ).all()
        ]
        assessments = [
            str(row[0])
            for row in session.execute(
                select(finance.Assessment.id).where(
                    finance.Assessment.application_id.in_(ordered)
                )
            ).all()
        ]
        decisions = [
            str(row[0])
            for row in session.execute(
                select(permit.Decision.id).where(
                    permit.Decision.application_id.in_(ordered)
                )
            ).all()
        ]
        permits = [
            str(row[0])
            for row in session.execute(
                select(permit.Permit.id).where(permit.Permit.application_id.in_(ordered))
            ).all()
        ]
    return {
        "applications": ordered,
        "evaluations": sorted(evaluations),
        "assessments": sorted(assessments),
        "decisions": sorted(decisions),
        "permits": sorted(permits),
    }


__all__ = [
    "AttributeRule",
    "ENTITY_ATTRIBUTES",
    "affected_dependents",
    "build_trusted_view",
    "crosswalk_view",
    "current_accepted_snapshot",
    "policy_for",
]
