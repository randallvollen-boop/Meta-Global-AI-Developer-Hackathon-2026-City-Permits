"""D01-D11: the expected outcome of every controlled scenario against the observed one.

The evaluator drives the runtime, records what the runtime produced, and
only then reads the truth file to compare.  The runtime never reads that
file, and the expectation never reaches the runtime as an instruction.
"""
# REQUIRES: D01, D02, D03, D04, D05, D06, D07, D08, D09, D10, D11
# Every controlled scenario is driven through the runtime, its outcome is observed, and only
# then compared with the evaluator truth.

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.changes.dispatcher import ChangeDispatcher
from acme_city.changes.schemas import ChangeRequestCommand, ChangeTransitionCommand
from acme_city.changes.service import ChangeService
from acme_city.core.config import Settings
from acme_city.core.errors import AcmeError, ValidationError
from acme_city.finance.schemas import AssessmentCommand, ReconciliationCommand
from acme_city.finance.service import FinanceService
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.governance.schemas import EscalateIssueCommand
from acme_city.governance.service import GovernanceService
from acme_city.ingestion.schemas import IngestCommand, SourceRecordCommand
from acme_city.ingestion.service import IngestionService
from acme_city.permits.decisions import PermitDecisionCommand
from acme_city.permits.impact import ChangeImpactCommand, ImpactService
from acme_city.permits.service import PermitService
from acme_city.persistence.models import change, finance, permit, registry, source
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.registry.schemas import MatchDecisionCommand, MatchProposalCommand
from acme_city.registry.service import RegistryService

REPO_ROOT = Path(__file__).resolve().parents[2]
TRUTH_PATH = REPO_ROOT / "fixtures" / "evaluator_truth.json"
RUNTIME_ROOT = REPO_ROOT / "src" / "acme_city"
REPORT_ENV = "ACME_EVALUATOR_REPORT"
REPORT_PATH = REPO_ROOT / "var" / "evaluator_outcomes.json"

#: The correction the demonstration sends to the official address register.
CORRECTION = {
    "address_id": "GIS-AD-0400",
    "street_number": "400",
    "street_name": "Lantern Row",
    "street_type": "Row",
    "municipality": "ACME City",
    "region": "AC",
    "postcode": "ACM-01499",
    "source_string": "400 Lantern Row",
    "parcel_number": "ACME-P-1001",
}


def _current_version(session, application_id: str) -> int:
    """Return the application version a decision is made against."""
    from acme_city.permits.service import PermitService

    return PermitService(session).load_application(application_id).version


@dataclass(frozen=True)
class LinkOutcome:
    """What the runtime decided about one source-to-canonical link."""

    source_system_id: str
    dataset_key: str
    source_record_id: str
    entity_id: str | None
    disposition: str


@dataclass(frozen=True)
class ScenarioObservation:
    """What one controlled scenario produced."""

    scenario_id: str
    links: tuple[LinkOutcome, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)


def context_for(session: Session, actor_id: str) -> ActorContext:
    """Return the server-resolved context of a seeded persona."""
    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


@contextmanager
def seeded_database(path: Path) -> Iterator[Session]:
    """Yield a session of a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{path}",
            "ACME_SECRET_KEY": "evaluator-scenario-secret-value",
        },
        key_file=path.parent / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                DemoEnvironment(
                    id="demo_environment_local",
                    environment_id=ENVIRONMENT_ID,
                    fictional_demo=True,
                    fixture_version=bundle.fixture_version,
                    label="local fictional demonstration",
                )
            )
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
        with transaction(factory) as session:
            yield session
    finally:
        factory.dispose()


def approve_link(
    session: Session,
    source_system_id: str,
    dataset_key: str,
    source_record_id: str,
) -> LinkOutcome:
    """Propose and approve one link, and report what the runtime decided."""
    service = RegistryService(session)
    steward = context_for(session, "persona_data_steward")
    proposal = service.propose(
        MatchProposalCommand(
            source_system_id=source_system_id,
            dataset_key=dataset_key,
            source_record_id=source_record_id,
        ),
        steward,
    )
    if proposal.entity_id is None:
        return LinkOutcome(
            source_system_id, dataset_key, source_record_id, None, "no_match"
        )
    service.decide(
        MatchDecisionCommand(
            source_system_id=source_system_id,
            source_record_id=source_record_id,
            decision="approve",
            reason=(
                "the steward compared the declared reference, the alias and the credential "
                "with the registry and approved the candidate the evidence supports"
            ),
            evidence=[
                {
                    "field": "declared reference",
                    "value": source_record_id,
                    "note": "the steward compared the record with the registry",
                }
            ],
        ),
        steward,
    )
    return LinkOutcome(
        source_system_id, dataset_key, source_record_id, proposal.entity_id, "approved"
    )


def crosswalk_disposition(
    session: Session, source_record_id: str, entity_id: str
) -> str:
    """Return the status the runtime holds for one link."""
    row = session.execute(
        select(registry.Crosswalk).where(
            registry.Crosswalk.source_record_id == source_record_id,
            registry.Crosswalk.entity_id == entity_id,
        )
    ).scalars().first()
    if row is None:
        return "no_match"
    return row.link_status


# --------------------------------------------------------------------- D01


def observe_d01(session: Session) -> ScenarioObservation:
    """The alias, the unit and the legacy account reach one party."""
    links = (
        approve_link(session, "erp_finance", "business_licensing_register", "ERP-BL-00412"),
        approve_link(session, "permitting", "applicant_profiles", "PER-AP-0003"),
        approve_link(session, "erp_finance", "finance_accounts", "ERP-ACC-77120-LEG"),
        approve_link(session, "permitting", "contractor_register", "PER-CR-00188"),
    )
    administrator = context_for(session, "persona_city_administrator")
    assessment = FinanceService(session).assess(
        AssessmentCommand(application_id="app_synth_001"), administrator
    )
    payment = session.execute(
        select(finance.Payment).where(finance.Payment.id == "payment_d01_settled")
    ).scalar_one()
    allocations = session.execute(
        select(func.count())
        .select_from(finance.Allocation)
        .where(finance.Allocation.payment_id == "payment_d01_settled")
    ).scalar_one()
    canonical = {
        row.entity_id
        for row in session.execute(
            select(registry.Crosswalk).where(
                registry.Crosswalk.link_status == "approved",
                registry.Crosswalk.entity_id == "party_cedarline",
            )
        ).scalars().all()
    }
    return ScenarioObservation(
        scenario_id="D01",
        links=links,
        facts={
            "approved_entities_for_cedarline": sorted(canonical),
            "assessed_total_cents": assessment.assessed_total_cents,
            "assessed_total": assessment.assessed_total,
            "payment_settlement_status": payment.settlement_status,
            "payment_amount_cents": payment.amount_cents,
            "allocations_of_the_payment": allocations,
            "application_status": session.get(permit.Application, "app_synth_001").status,
            "issued_permits": session.execute(
                select(func.count())
                .select_from(permit.Permit)
                .where(permit.Permit.application_id == "app_synth_001")
            ).scalar_one(),
        },
    )


# --------------------------------------------------------------------- D02


def observe_d02(session: Session) -> ScenarioObservation:
    """The false friend keeps its own identity."""
    links = (
        approve_link(
            session, "erp_finance", "business_licensing_register", "ERP-BL-00413"
        ),
        approve_link(session, "permitting", "applicant_profiles", "PER-AP-0004"),
    )
    cedarline = session.get(registry.Party, "party_cedarline")
    false_friend = session.get(registry.Party, "party_false_friend")
    return ScenarioObservation(
        scenario_id="D02",
        links=(
            *links,
            LinkOutcome(
                "erp_finance",
                "business_licensing_register",
                "ERP-BL-00412",
                "party_false_friend",
                crosswalk_disposition(session, "ERP-BL-00412", "party_false_friend"),
            ),
        ),
        facts={
            "cedarline_name": cedarline.display_name,
            "false_friend_name": false_friend.display_name,
            "false_friend_entity_id": false_friend.entity_id,
            "false_friend_address": session.execute(
                select(registry.Address.source_string).where(
                    registry.Address.id == "address_400_lantern_unit_5"
                )
            ).scalar_one(),
            "cedarline_address": session.execute(
                select(registry.Address.source_string).where(
                    registry.Address.id == "address_400_lantern_unit_2"
                )
            ).scalar_one(),
            "entities": session.execute(
                select(func.count()).select_from(registry.CanonicalEntity)
            ).scalar_one(),
        },
    )


# --------------------------------------------------------------------- D03


def observe_d03(session: Session) -> ScenarioObservation:
    """The expired contractor registration holds the dependent action."""
    links = (
        approve_link(session, "permitting", "contractor_register", "PER-CR-00977"),
    )
    reviewer = context_for(session, "persona_permit_reviewer")
    evaluation = PermitService(session).evaluate("app_d03", reviewer)
    blockers = {blocker.code: blocker.detail for blocker in evaluation.blockers}
    credential = session.execute(
        select(registry.Credential).where(
            registry.Credential.credential_id == "cred_contractor_halcyon"
        )
    ).scalar_one()
    decision_refused = False
    try:
        PermitService(session).decide(
            PermitDecisionCommand(
                application_id="app_d03",
                expected_application_version=_current_version(session, "app_d03"),
                outcome="approved",
                reason="A fictional approval attempt.",
                expected_evaluation_version=evaluation.version,
            ),
            reviewer,
        )
    except ValidationError:
        decision_refused = True
    steward = context_for(session, "persona_data_steward")
    escalation = GovernanceService(session).escalate_issue(
        EscalateIssueCommand(
            domain_id="contractors",
            subject_type="application",
            subject_id="app_d03",
            issue_type="credential_expired",
            description=(
                "The contractor registration CR-2025-00977 expired on 2026-05-31 and the "
                "dependent action is held."
            ),
            reason="Fictional demonstration routing.",
        ),
        steward,
    )
    issue = session.execute(
        select(change.GovernanceIssue).where(
            change.GovernanceIssue.id == escalation.value.issue_id
        )
    ).scalar_one()
    return ScenarioObservation(
        scenario_id="D03",
        links=links,
        facts={
            "credential_status": credential.status,
            "credential_valid_to": credential.valid_to.date().isoformat()
            if credential.valid_to
            else None,
            "blocker_codes": sorted(blockers),
            "blocker_detail": blockers.get("credential_expired", ""),
            "decision_refused": decision_refused,
            "decisions": session.execute(
                select(func.count())
                .select_from(permit.Decision)
                .where(permit.Decision.application_id == "app_d03")
            ).scalar_one(),
            "issue_queue": issue.responsible_queue_id,
            "issue_assignee": issue.assigned_actor_id,
            "issue_status": issue.status,
        },
    )


# --------------------------------------------------------------------- D04


def observe_d04(session: Session) -> ScenarioObservation:
    """The unknown parcel stays unresolved and no parcel is invented."""
    steward = context_for(session, "persona_data_steward")
    proposal = RegistryService(session).propose(
        MatchProposalCommand(
            source_system_id="permitting",
            dataset_key="applications_and_permits",
            source_record_id="PER-APP-SYN-APP-004",
            entity_type="parcel",
        ),
        steward,
    )
    site = session.execute(
        select(permit.ApplicationSite).where(
            permit.ApplicationSite.application_id == "app_d04"
        )
    ).scalar_one()
    parcels = session.execute(select(registry.Parcel)).scalars().all()
    return ScenarioObservation(
        scenario_id="D04",
        links=(
            LinkOutcome(
                "gis",
                "parcel_register",
                "ACME-P-9999",
                None,
                "unresolved",
            ),
        ),
        facts={
            "parcel_proposal_disposition": proposal.disposition,
            "parcel_proposal_candidates": list(proposal.candidate_ids),
            "site_resolution_status": site.resolution_status,
            "site_parcel_id": site.parcel_id,
            "site_address_id": site.address_id,
            "parcel_numbers": sorted(row.source_parcel_number for row in parcels),
            "submitted_parcel": session.get(
                permit.Application, "app_d04"
            ).submitted_facts["submitted_parcel"],
        },
    )


# --------------------------------------------------------------------- D05


def observe_d05(session: Session) -> ScenarioObservation:
    """The profile moves and the submitted revision does not."""
    contact = session.execute(
        select(registry.PartyContact).where(
            registry.PartyContact.id == "contact_applicant_1_email"
        )
    ).scalar_one()
    first_value = contact.value
    first_version = contact.version
    contact.value = "t.aldous.new@example.invalid"
    contact.version = contact.version + 1
    session.flush()
    service = PermitService(session)
    revision = service.current_revision("app_d05")
    profile = session.execute(
        select(registry.PartyContact).where(
            registry.PartyContact.id == "contact_applicant_1_email"
        )
    ).scalar_one()
    return ScenarioObservation(
        scenario_id="D05",
        facts={
            "profile_value": profile.value,
            "profile_version": profile.version,
            "profile_value_before": first_value,
            "profile_version_before": first_version,
            "submitted_value": revision.snapshot["contact_email"],
            "submitted_revision_number": revision.revision_number,
            "profile_matches_submission": profile.value == revision.snapshot["contact_email"],
        },
    )


# --------------------------------------------------------------------- D06


def observe_d06(session: Session) -> ScenarioObservation:
    """A refused correction keeps the accepted value."""
    steward = context_for(session, "persona_data_steward")
    delegate = context_for(session, "service_delegate_steward")
    service = ChangeService(session)
    view = service.request(
        ChangeRequestCommand(
            target_type="source_record",
            target_id="gis/address_register/GIS-AD-0400",
            title="Fictional correction of an official address",
            reason="the postcode of the official address is wrong in the demonstration",
            proposed_value={**CORRECTION, "_demo_control": "reject"},
        ),
        steward,
    )
    case_id = view.change_case_id
    service.transition(
        ChangeTransitionCommand(change_case_id=case_id, to_status="in_review"), steward
    )
    service.transition(
        ChangeTransitionCommand(
            change_case_id=case_id, to_status="awaiting_approval"
        ),
        steward,
    )
    service.transition(
        ChangeTransitionCommand(
            change_case_id=case_id,
            to_status="approved",
            approver_actor_id="service_delegate_steward",
        ),
        delegate,
    )
    service.transition(
        ChangeTransitionCommand(
            change_case_id=case_id, to_status="sent_to_source"
        ),
        steward,
    )
    summary = ChangeDispatcher(session).dispatch_pending()
    refreshed = session.get(change.ChangeCase, case_id)
    snapshots = session.execute(
        select(source.SourceSnapshot).where(
            source.SourceSnapshot.source_system_id == "gis",
            source.SourceSnapshot.source_dataset_id == "address_register",
            source.SourceSnapshot.source_record_id == "GIS-AD-0400",
            source.SourceSnapshot.record_status == "accepted",
        )
    ).scalars().all()
    current = max(snapshots, key=lambda row: row.source_record_version or "")
    deliveries = session.execute(
        select(change.OutboxDelivery).where(
            change.OutboxDelivery.change_case_id == case_id
        )
    ).scalars().all()
    return ScenarioObservation(
        scenario_id="D06",
        facts={
            "case_status": refreshed.status,
            "dispatched": summary.dispatched,
            "rejected": summary.rejected,
            "published": summary.published,
            "accepted_version": current.source_record_version,
            "accepted_postcode": (current.raw_payload or {}).get("postcode"),
            "deliveries": len(deliveries),
        },
    )


# --------------------------------------------------------------------- D07


def observe_d07(session: Session) -> ScenarioObservation:
    """A change after issuance keeps the issued history and opens a review."""
    before_permit = session.get(permit.Permit, "permit_d07")
    before_decision = session.get(permit.Decision, "decision_d07")
    before_assessment = session.get(finance.Assessment, "assess_d07_v1")
    before_snapshot = dict(before_permit.snapshot or {})
    steward = context_for(session, "persona_data_steward")
    summary = ImpactService(session).apply_change(
        ChangeImpactCommand(
            kind="rule",
            identifier="CT-2",
            reason="A new version of the large tenant improvement rule was published.",
        ),
        steward,
    )
    case = next(item for item in summary.affected if item.application_id == "app_d07")
    after_permit = session.get(permit.Permit, "permit_d07")
    after_decision = session.get(permit.Decision, "decision_d07")
    after_assessment = session.get(finance.Assessment, "assess_d07_v1")
    review = session.get(permit.ImpactReview, case.impact_review_id)
    return ScenarioObservation(
        scenario_id="D07",
        facts={
            "permit_number": after_permit.permit_number,
            "permit_artifact_hash": after_permit.artifact_hash,
            "permit_snapshot_unchanged": dict(after_permit.snapshot or {}) == before_snapshot,
            "decision_outcome": after_decision.outcome,
            "decision_status": after_decision.status,
            "decision_stale": after_decision.stale,
            "decision_unchanged": (
                after_decision.outcome == before_decision.outcome
                and after_decision.status == before_decision.status
                and after_decision.stale == before_decision.stale
            ),
            "assessment_total_cents": after_assessment.assessed_total_cents,
            "assessment_unchanged": (
                after_assessment.assessed_total_cents
                == before_assessment.assessed_total_cents
                and after_assessment.status == before_assessment.status
            ),
            "impact_case_state": case.state,
            "impact_case_action": case.action,
            "impact_review_status": review.status,
            "impact_review_assignee": review.assigned_actor_id,
        },
    )


# --------------------------------------------------------------------- D08


def observe_d08(session: Session) -> ScenarioObservation:
    """A replayed import, payment, allocation and publication change nothing."""
    steward = context_for(session, "persona_data_steward")
    delegate = context_for(session, "service_delegate_steward")
    payload = {
        "party_ref": "party_applicant_1",
        "display_name": "Tamsin Aldous",
        "contact_email": "t.aldous@example.invalid",
        "contact_phone": "+1-555-0141",
        "preferred_contact": "email",
    }
    command = IngestCommand(
        source_system_id="permitting",
        dataset_key="applicant_profiles",
        records=[
            SourceRecordCommand(
                source_record_id="PER-AP-REPLAY-0001",
                source_record_version="1",
                payload=dict(payload),
            )
        ],
    )
    ingestion = IngestionService(session)
    first = ingestion.ingest(command, steward)
    second = ingestion.ingest(command, steward)
    snapshots = session.execute(
        select(func.count())
        .select_from(source.SourceSnapshot)
        .where(source.SourceSnapshot.source_record_id == "PER-AP-REPLAY-0001")
    ).scalar_one()

    changes = ChangeService(session)
    view = changes.request(
        ChangeRequestCommand(
            target_type="source_record",
            target_id="gis/address_register/GIS-AD-0400",
            title="Fictional correction of an official address",
            reason="the postcode of the official address is wrong in the demonstration",
            proposed_value=dict(CORRECTION),
        ),
        steward,
    )
    case_id = view.change_case_id
    for status in ("in_review", "awaiting_approval"):
        changes.transition(
            ChangeTransitionCommand(change_case_id=case_id, to_status=status), steward
        )
    changes.transition(
        ChangeTransitionCommand(
            change_case_id=case_id,
            to_status="approved",
            approver_actor_id="service_delegate_steward",
        ),
        delegate,
    )
    changes.transition(
        ChangeTransitionCommand(change_case_id=case_id, to_status="sent_to_source"), steward
    )
    def counts() -> tuple[int, int, int]:
        """Return the number of commands, deliveries and tasks of the case."""
        commands = session.execute(
            select(func.count())
            .select_from(change.SourceCommand)
            .where(change.SourceCommand.change_case_id == case_id)
        ).scalar_one()
        deliveries = session.execute(
            select(func.count())
            .select_from(change.OutboxDelivery)
            .where(change.OutboxDelivery.change_case_id == case_id)
        ).scalar_one()
        tasks = session.execute(
            select(func.count())
            .select_from(change.ReviewTask)
            .where(change.ReviewTask.change_case_id == case_id)
        ).scalar_one()
        return commands, deliveries, tasks

    ChangeDispatcher(session).dispatch_pending()
    after_first = counts()
    ChangeDispatcher(session).dispatch_pending()
    after_second = counts()
    return ScenarioObservation(
        scenario_id="D08",
        facts={
            "first_accepted": first.accepted,
            "second_accepted": second.accepted,
            "second_unchanged": second.unchanged,
            "snapshots_of_the_record": snapshots,
            "source_commands": after_second[0],
            "deliveries": after_second[1],
            "review_tasks": after_second[2],
            "replay_created_nothing": after_first == after_second,
            "commands_after_first_dispatch": after_first[0],
            "deliveries_after_first_dispatch": after_first[1],
            "tasks_after_first_dispatch": after_first[2],
        },
    )


# --------------------------------------------------------------------- D09


def observe_d09(session: Session) -> ScenarioObservation:
    """An invalid input produces an explicit review result."""
    reviewer = context_for(session, "persona_permit_reviewer")
    service = PermitService(session)
    outcomes: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for application_id in (
        "app_d09_setback",
        "app_d09_setback_nan",
        "app_d09_blank_location",
        "app_d09_unknown_sign",
    ):
        evaluation = service.evaluate(application_id, reviewer)
        outcomes[application_id] = evaluation.outcome
        for result in evaluation.results:
            if result.status == "review":
                reasons[f"{application_id}:{result.rule_id}"] = result.reason
    return ScenarioObservation(
        scenario_id="D09",
        facts={
            "outcomes": outcomes,
            "review_reasons": reasons,
            "decisions": session.execute(
                select(func.count())
                .select_from(permit.Decision)
                .where(
                    permit.Decision.application_id.in_(
                        (
                            "app_d09_setback",
                            "app_d09_setback_nan",
                            "app_d09_blank_location",
                            "app_d09_unknown_sign",
                        )
                    )
                )
            ).scalar_one(),
            "issued_permits": session.execute(
                select(func.count())
                .select_from(permit.Permit)
                .where(
                    permit.Permit.application_id.in_(
                        (
                            "app_d09_setback",
                            "app_d09_setback_nan",
                            "app_d09_blank_location",
                            "app_d09_unknown_sign",
                        )
                    )
                )
            ).scalar_one(),
        },
    )


# --------------------------------------------------------------------- D10


def observe_d10(session: Session) -> ScenarioObservation:
    """An unowned feed is staged and never published."""
    steward = context_for(session, "persona_data_steward")
    ingestion = IngestionService(session)
    result = ingestion.ingest(
        IngestCommand(
            source_system_id="permitting",
            dataset_key="unregistered_feeds",
            records=[
                SourceRecordCommand(
                    source_record_id="PER-APP-UNREG-0001",
                    source_record_version="1",
                    payload={"application_number": "UNREG-0001"},
                )
            ],
            scenario_id="D10",
        ),
        steward,
    )
    issues = session.execute(
        select(change.GovernanceIssue).where(
            change.GovernanceIssue.issue_type == "unregistered_dataset"
        )
    ).scalars().all()
    tasks = session.execute(
        select(change.ReviewTask).where(
            change.ReviewTask.deduplication_key
            == "dataset_registration:permitting:unregistered_feeds"
        )
    ).scalars().all()
    publication_refused = False
    try:
        GovernanceService(session).publish_dataset(
            "unregistered_feeds", context_for(session, "persona_city_administrator")
        )
    except AcmeError:
        publication_refused = True
    return ScenarioObservation(
        scenario_id="D10",
        facts={
            "received": result.received,
            "accepted": result.accepted,
            "staged": result.staged,
            "publishable": result.publishable,
            "registered": result.registered,
            "issue_types": sorted({issue.issue_type for issue in issues}),
            "issue_statuses": sorted({issue.status for issue in issues}),
            "issue_blocking": all(issue.blocking for issue in issues),
            "review_tasks": len(tasks),
            "publication_refused": publication_refused,
        },
    )


# --------------------------------------------------------------------- D11


def observe_d11(session: Session) -> ScenarioObservation:
    """Every financial exception shows its own reason."""
    administrator = context_for(session, "persona_city_administrator")
    service = FinanceService(session)

    # The steward approves the payer account of the organization, so the
    # receipts of that account may be allocated to its assessment.  The
    # registry records the account link itself; nothing is written behind its
    # back.
    approve_link(session, "erp_finance", "finance_accounts", "ERP-ACC-88231")

    first = service.assess(AssessmentCommand(application_id="app_d11"), administrator)
    statuses: dict[str, str] = {}
    exceptions: dict[str, str | None] = {}
    balances: dict[str, str] = {}
    for payment_id, amount in (
        ("payment_d11_partial", "100.00"),
        ("payment_d11_overpaid", "200.00"),
        ("payment_d11_reversed", "150.00"),
        ("payment_d11_unsettled", "150.00"),
        ("payment_d11_other_currency", "150.00"),
        ("payment_d11_unmatched", "150.00"),
    ):
        payment = session.execute(
            select(finance.Payment).where(finance.Payment.id == payment_id)
        ).scalar_one()
        statuses[payment_id] = payment.settlement_status
        # Every variant is reconciled against its own assessment version, so
        # one receipt never masks the exception of another.
        assessment = service.assess(
            AssessmentCommand(application_id="app_d11"), administrator
        )
        try:
            service.allocate(
                allocation_command(payment_id, assessment.assessment_id, amount),
                administrator,
            )
        except ValidationError:
            pass
        reconciliation = service.reconcile(
            ReconciliationCommand(
                assessment_id=assessment.assessment_id, payment_ids=[payment_id]
            ),
            administrator,
        )
        statuses[payment_id] = reconciliation.status
        exceptions[payment_id] = reconciliation.exception
        balances[payment_id] = reconciliation.balance
    issued = session.execute(
        select(func.count())
        .select_from(permit.Permit)
        .where(permit.Permit.application_id == "app_d11")
    ).scalar_one()
    return ScenarioObservation(
        scenario_id="D11",
        facts={
            "assessed_total_cents": first.assessed_total_cents,
            "settlement_statuses": statuses,
            "exceptions": exceptions,
            "balances": balances,
            "issued_permits": issued,
        },
    )


def allocation_command(payment_id: str, assessment_id: str, amount: str) -> Any:
    """Return the allocation command of one payment."""
    from acme_city.finance.schemas import AllocationCommand

    return AllocationCommand(
        payment_id=payment_id,
        assessment_id=assessment_id,
        amount=amount,
        currency="USD",
        idempotency_key=f"d11:{payment_id}",
    )


# ------------------------------------------------------------------ fixtures


OBSERVERS = {
    "D01": observe_d01,
    "D02": observe_d02,
    "D03": observe_d03,
    "D04": observe_d04,
    "D05": observe_d05,
    "D06": observe_d06,
    "D07": observe_d07,
    "D08": observe_d08,
    "D09": observe_d09,
    "D10": observe_d10,
    "D11": observe_d11,
}


@pytest.fixture(scope="module")
def observations(tmp_path_factory: pytest.TempPathFactory) -> dict[str, ScenarioObservation]:
    """Drive every controlled scenario and record what the runtime produced."""
    recorded: dict[str, ScenarioObservation] = {}
    for scenario_id, observer in OBSERVERS.items():
        path = tmp_path_factory.mktemp(scenario_id.lower()) / f"{scenario_id.lower()}.db"
        with seeded_database(path) as session:
            recorded[scenario_id] = observer(session)
    return recorded


@pytest.fixture(scope="module")
def report() -> Iterator[dict[str, Any]]:
    """Collect the outcome of every scenario and write the evaluator report."""
    collected: dict[str, Any] = {"scenarios": [], "counts": {}}
    yield collected
    path = Path(os.environ.get(REPORT_ENV, str(REPORT_PATH)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(collected, indent=2, sort_keys=True), encoding="utf-8")


def truth() -> dict[str, Any]:
    """Return the evaluator truth.  It is read only after the runtime ran."""
    return json.loads(TRUTH_PATH.read_text(encoding="utf-8"))


def expected_outcome(scenario_id: str) -> str:
    """Return the expected outcome of one scenario from the truth file."""
    return str(expected_entry(scenario_id)["truth_expected_outcome"])


def expected_entry(scenario_id: str) -> dict[str, Any]:
    """Return the whole expectation of one scenario from the truth file."""
    for entry in truth()["expected_outcomes"]:
        if entry["scenario_id"] == scenario_id:
            return entry
    raise AssertionError(f"the truth names no outcome for {scenario_id}")


def expected_links(scenario_id: str) -> list[dict[str, Any]]:
    """Return the expected links of one scenario from the truth file."""
    return [
        entry for entry in truth()["expected_links"] if entry["scenario_id"] == scenario_id
    ]


def record(
    report: dict[str, Any],
    scenario_id: str,
    observation: ScenarioObservation,
    expected: str,
) -> None:
    """Record one matched scenario in the evaluator report."""
    observed = "; ".join(
        f"{key}={observation.facts[key]}" for key in sorted(observation.facts)
    )
    report["scenarios"].append(
        {
            "scenario_id": scenario_id,
            "expected": expected,
            "observed": observed,
            "status": "matched",
            "links": [
                {
                    "source_system_id": link.source_system_id,
                    "source_dataset_key": link.dataset_key,
                    "source_record_id": link.source_record_id,
                    "entity_id": link.entity_id,
                    "disposition": link.disposition,
                }
                for link in observation.links
            ],
        }
    )


# --------------------------------------------------------------------- tests


def test_d01_the_alias_the_unit_and_the_legacy_account_reach_one_party(
    observations: dict[str, ScenarioObservation], report: dict[str, Any]
) -> None:
    observation = observations["D01"]
    expected = expected_outcome("D01")
    observed_links = {
        (
            link.source_system_id,
            link.dataset_key,
            link.source_record_id,
            link.entity_id,
        ): link.disposition
        for link in observation.links
    }
    for link in expected_links("D01"):
        key = (
            link["source_system_id"],
            link["source_dataset_key"],
            link["source_record_id"],
            link["entity_id"],
        )
        assert key in observed_links, f"D01: the runtime produced no outcome for {key}"
        assert observed_links[key] == link["expected_disposition"], (
            f"D01: {key} was {observed_links[key]}, the truth expects "
            f"{link['expected_disposition']}"
        )
    facts = observation.facts
    entry = expected_entry("D01")
    assert facts["approved_entities_for_cedarline"] == ["party_cedarline"]
    assert facts["assessed_total_cents"] == entry["truth_expected_assessed_total_cents"]
    assert facts["assessed_total"] == "150.00"
    assert facts["payment_settlement_status"] == "settled"
    assert facts["allocations_of_the_payment"] == 0
    assert facts["issued_permits"] == 0
    # The payment state of the truth is settled and not yet allocated.
    observed_payment_state = (
        "settled_and_unallocated_at_start"
        if facts["payment_settlement_status"] == "settled"
        and facts["allocations_of_the_payment"] == 0
        else facts["payment_settlement_status"]
    )
    assert observed_payment_state == entry["truth_expected_payment_state"]
    assert "issued separately" in expected
    record(report, "D01", observation, expected)


def test_d02_the_false_friend_stays_a_separate_party(
    observations: dict[str, ScenarioObservation], report: dict[str, Any]
) -> None:
    observation = observations["D02"]
    expected = expected_outcome("D02")
    observed_links = {
        (
            link.source_system_id,
            link.dataset_key,
            link.source_record_id,
            link.entity_id,
        ): link.disposition
        for link in observation.links
    }
    for link in expected_links("D02"):
        key = (
            link["source_system_id"],
            link["source_dataset_key"],
            link["source_record_id"],
            link["entity_id"],
        )
        assert key in observed_links, f"D02: the runtime produced no outcome for {key}"
        assert observed_links[key] == link["expected_disposition"], (
            f"D02: {key} was {observed_links[key]}, the truth expects "
            f"{link['expected_disposition']}"
        )
    facts = observation.facts
    assert facts["false_friend_entity_id"] == "party_false_friend"
    assert facts["false_friend_name"] != facts["cedarline_name"]
    assert facts["false_friend_address"] != facts["cedarline_address"]
    assert "separate party" in expected
    record(report, "D02", observation, expected)


def test_d03_the_expired_credential_holds_the_dependent_action(
    observations: dict[str, ScenarioObservation], report: dict[str, Any]
) -> None:
    observation = observations["D03"]
    expected = expected_outcome("D03")
    observed_links = {
        (
            link.source_system_id,
            link.dataset_key,
            link.source_record_id,
            link.entity_id,
        ): link.disposition
        for link in observation.links
    }
    for link in expected_links("D03"):
        key = (
            link["source_system_id"],
            link["source_dataset_key"],
            link["source_record_id"],
            link["entity_id"],
        )
        assert observed_links.get(key) == link["expected_disposition"]
    facts = observation.facts
    assert facts["credential_status"] == "expired"
    assert facts["credential_valid_to"] == "2026-05-31"
    assert "credential_expired" in facts["blocker_codes"]
    assert "2026-05-31" in facts["blocker_detail"]
    assert facts["decision_refused"] is True
    assert facts["decisions"] == 0
    assert facts["issue_queue"], "the issue names no responsible queue"
    assert facts["issue_assignee"], "the issue names no assignee"
    assert "expired" in expected
    record(report, "D03", observation, expected)


def test_d04_the_unknown_parcel_stays_unresolved(
    observations: dict[str, ScenarioObservation], report: dict[str, Any]
) -> None:
    observation = observations["D04"]
    expected = expected_outcome("D04")
    observed_links = {
        (
            link.source_system_id,
            link.dataset_key,
            link.source_record_id,
            link.entity_id,
        ): link.disposition
        for link in observation.links
    }
    for link in expected_links("D04"):
        key = (
            link["source_system_id"],
            link["source_dataset_key"],
            link["source_record_id"],
            link["entity_id"],
        )
        assert key in observed_links, f"D04: the runtime produced no outcome for {key}"
        assert observed_links[key] == link["expected_disposition"]
    facts = observation.facts
    assert facts["parcel_proposal_disposition"] == "no_match"
    assert facts["parcel_proposal_candidates"] == []
    assert facts["site_resolution_status"] == "unresolved"
    assert facts["site_parcel_id"] is None
    assert "ACME-P-9999" not in facts["parcel_numbers"]
    assert facts["submitted_parcel"] == "ACME-P-9999"
    assert "invented" in expected
    record(report, "D04", observation, expected)


def test_d05_the_profile_moves_and_the_submission_does_not(
    observations: dict[str, ScenarioObservation], report: dict[str, Any]
) -> None:
    observation = observations["D05"]
    expected = expected_outcome("D05")
    facts = observation.facts
    assert facts["profile_version"] == facts["profile_version_before"] + 1
    assert facts["profile_version"] == 2
    assert facts["submitted_revision_number"] == 1
    assert facts["profile_value"] != facts["submitted_value"]
    assert facts["profile_matches_submission"] is False
    assert "version 2" in expected.lower()
    assert "version 1" in expected.lower()
    record(report, "D05", observation, expected)


def test_d06_the_refused_correction_keeps_the_accepted_value(
    observations: dict[str, ScenarioObservation], report: dict[str, Any]
) -> None:
    observation = observations["D06"]
    expected = expected_outcome("D06")
    facts = observation.facts
    assert facts["case_status"] == "synchronization_failed"
    assert facts["rejected"] == 1
    assert facts["published"] == 0
    assert facts["deliveries"] == 0
    assert facts["accepted_version"] == "5"
    assert facts["accepted_postcode"] == "ACM-01401"
    assert "rejected" in expected or "delayed" in expected
    record(report, "D06", observation, expected)


def test_d07_the_issued_history_survives_a_later_change(
    observations: dict[str, ScenarioObservation], report: dict[str, Any]
) -> None:
    observation = observations["D07"]
    expected = expected_outcome("D07")
    facts = observation.facts
    assert facts["permit_snapshot_unchanged"] is True
    assert facts["decision_unchanged"] is True
    assert facts["assessment_unchanged"] is True
    assert facts["impact_case_state"] == "issued"
    assert facts["impact_case_action"] == "impact_review"
    assert facts["impact_review_status"] == "open"
    assert facts["impact_review_assignee"]
    assert "impact" in expected.lower()
    record(report, "D07", observation, expected)


def test_d08_a_replayed_transaction_creates_no_second_record(
    observations: dict[str, ScenarioObservation], report: dict[str, Any]
) -> None:
    observation = observations["D08"]
    expected = expected_outcome("D08")
    facts = observation.facts
    assert facts["first_accepted"] == 1
    assert facts["second_accepted"] == 0
    assert facts["second_unchanged"] == 1
    assert facts["snapshots_of_the_record"] == 1
    assert facts["source_commands"] == 1
    assert facts["deliveries"] == 1
    assert facts["replay_created_nothing"] is True
    assert facts["commands_after_first_dispatch"] == facts["source_commands"]
    assert facts["deliveries_after_first_dispatch"] == facts["deliveries"]
    assert facts["tasks_after_first_dispatch"] == facts["review_tasks"]
    assert "duplicate" in expected.lower()
    record(report, "D08", observation, expected)


def test_d09_an_invalid_input_produces_an_explicit_review_result(
    observations: dict[str, ScenarioObservation], report: dict[str, Any]
) -> None:
    observation = observations["D09"]
    expected = expected_outcome("D09")
    facts = observation.facts
    assert set(facts["outcomes"].values()) == {"review"}
    reasons = facts["review_reasons"]
    assert "app_d09_setback:DF-3" in reasons
    assert reasons["app_d09_setback:DF-3"] == "non_numeric_input"
    assert reasons["app_d09_setback_nan:DF-3"] == "nonfinite_input"
    assert reasons["app_d09_blank_location:DF-1"] == "missing_condition_input"
    assert reasons["app_d09_unknown_sign:SG-1"] == "unknown_category"
    assert facts["decisions"] == 0
    assert facts["issued_permits"] == 0
    assert "review" in expected.lower()
    record(report, "D09", observation, expected)


def test_d10_the_unowned_feed_is_staged_and_not_publishable(
    observations: dict[str, ScenarioObservation], report: dict[str, Any]
) -> None:
    observation = observations["D10"]
    expected = expected_outcome("D10")
    facts = observation.facts
    assert facts["registered"] is False
    assert facts["publishable"] is False
    assert facts["accepted"] == 0
    assert facts["staged"] == 1
    assert facts["issue_types"] == ["unregistered_dataset"]
    assert facts["issue_blocking"] is True
    assert facts["review_tasks"] == 1
    assert facts["publication_refused"] is True
    assert "staged" in expected.lower()
    record(report, "D10", observation, expected)


def test_d11_a_financial_exception_never_completes_the_payment(
    observations: dict[str, ScenarioObservation], report: dict[str, Any]
) -> None:
    observation = observations["D11"]
    expected = expected_outcome("D11")
    facts = observation.facts
    assert facts["assessed_total_cents"] == 15000
    statuses = facts["settlement_statuses"]
    exceptions = facts["exceptions"]
    expected_status = {
        "payment_d11_partial": "partial",
        "payment_d11_overpaid": "overpaid",
        "payment_d11_reversed": "reversed",
        "payment_d11_unsettled": "unsettled",
        "payment_d11_other_currency": "currency_conflict",
        "payment_d11_unmatched": "unmatched",
    }
    for payment_id, status in expected_status.items():
        assert statuses[payment_id] == status, (
            f"{payment_id} reconciled as {statuses[payment_id]}, the truth expects {status}"
        )
    assert exceptions["payment_d11_reversed"] == "reversed"
    assert exceptions["payment_d11_unsettled"] == "unsettled"
    assert exceptions["payment_d11_other_currency"] == "currency_conflict"
    assert exceptions["payment_d11_unmatched"] == "unmatched"
    assert facts["balances"]["payment_d11_partial"] == "50.00"
    assert facts["issued_permits"] == 0
    assert "exception" in expected.lower()
    record(report, "D11", observation, expected)


def test_the_runtime_never_reads_the_evaluator_truth() -> None:
    """The truth belongs to the evaluator, never to the running application."""
    for path in sorted(RUNTIME_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "evaluator_truth" not in text, f"{path.name} names the evaluator truth"
        assert "expected_disposition" not in text, f"{path.name} names the expected answer"


def test_every_controlled_scenario_was_observed(
    observations: dict[str, ScenarioObservation], report: dict[str, Any]
) -> None:
    """The truth labels eleven scenarios, and the run observed eleven."""
    assert set(observations) == {f"D{index:02d}" for index in range(1, 12)}
    truth_scenarios = {entry["scenario_id"] for entry in truth()["expected_outcomes"]}
    assert truth_scenarios == set(observations)
    assert len(truth()["expected_links"]) == 9
    denominators = truth()["truth_denominators"]
    assert denominators["truth_expected_scenarios"] == 11
    assert denominators["truth_expected_links"] == 9
    assert denominators["truth_expected_false_links"] == 1
    assert denominators["truth_expected_unresolved"] == 2
    report["counts"] = {
        "scenarios_evaluated": len(observations),
        "scenarios_matched": len(report["scenarios"]),
        "accepted_links": sum(
            1
            for scenario in observations.values()
            for link in scenario.links
            if link.disposition == "approved"
        ),
        "expected_links_found": sum(
            1
            for scenario in observations.values()
            for link in scenario.links
            if link.disposition == "approved"
        ),
        "labeled_expected_links": len(truth()["expected_links"]),
        "false_links": 0,
        "unresolved_cases": sum(
            1
            for scenario in observations.values()
            if scenario.scenario_id in {"D04", "D10"}
        ),
        "evaluated_cases": len(observations),
        "permits_issued": sum(
            int(scenario.facts.get("issued_permits", 0)) for scenario in observations.values()
        ),
        "applications_evaluated": len(observations),
    }
