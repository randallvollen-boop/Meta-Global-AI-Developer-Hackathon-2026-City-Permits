"""The deterministic recommendations of the steward assistant.

Every kind of task of the queue is covered: the recommendation names what the
assistant proposes, how sure it is, the evidence it read and the version of
the record it read.  The recommendation never decides anything: the steward
does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.changes.schemas import ChangeRequestCommand
from acme_city.changes.service import ChangeService
from acme_city.core.config import Settings
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_automation_demo import seed_automation
from acme_city.ingestion.schemas import IngestCommand, SourceRecordCommand
from acme_city.ingestion.service import IngestionService
from acme_city.persistence.models import change, gis, registry, registry_automation
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.registry import automation, steward_assist
from acme_city.registry.schemas import MatchProposalCommand
from acme_city.registry.service import RegistryService

STEWARD = ActorContext(actor_id="persona_data_steward", role_ids=frozenset({"domain_steward"}))

#: The keys of the evidence of every kind of task.
LINK_EVIDENCE_KEYS = {
    "source_system",
    "source_dataset",
    "source_record_id",
    "source_version",
    "candidate_entity_id",
    "candidate_label",
    "score",
    "next_best_score",
    "auto_apply_threshold",
    "suggest_threshold",
    "policy_decision",
    "reasons",
    "failed_checks",
    "agreements",
    "disagreements",
}

AUTOMATIC_LINK_EVIDENCE_KEYS = {
    "application_id",
    "crosswalk_id",
    "entity_id",
    "entity_label",
    "source_record_id",
    "score",
    "decision",
    "policy_version",
    "reasons",
    "failed_checks",
    "agreements",
    "disagreements",
}

PARCEL_EVIDENCE_KEYS = {
    "application_id",
    "submitted_text",
    "matched_address",
    "parcel_id",
    "parcel_number",
    "stated_parcel",
    "score",
    "locator_status",
    "link_state",
    "note",
    "conflict",
    "auto_apply_threshold",
    "suggest_threshold",
    "candidates",
}

CASE_EVIDENCE_KEYS = {
    "change_case_id",
    "target_type",
    "target_id",
    "change_kind",
    "current_value",
    "proposed_value",
    "expected_version",
    "current_version",
    "destination",
    "evidence",
}

ISSUE_EVIDENCE_KEYS = {
    "issue_id",
    "issue_type",
    "subject_type",
    "subject_id",
    "description",
    "responsible_queue_id",
    "assigned_actor_id",
    "owner",
    "blocking",
    "classification",
    "request_draft",
}

#: The payload of a business licence that no master record holds.
UNKNOWN_LICENCE = {
    "holder_ref": "party_hollis",
    "license_number": "BL-2026-00900",
    "status": "active",
    "valid_from": "2026-01-01",
    "valid_to": "2026-12-31",
}

#: The payload of a business licence whose number no master record holds.
CONFLICTING_LICENCE = {
    "holder_ref": "party_cedarline",
    "license_number": "BL-9999-99999",
    "status": "active",
    "valid_from": "2026-01-01",
    "valid_to": "2026-12-31",
}

#: The payload of a business licence that names nobody the City knows.
UNKNOWN_HOLDER = {
    "holder_name": "Nobody At All",
    "license_number": "BL-0000-00000",
    "status": "active",
    "valid_from": "2026-01-01",
    "valid_to": "2026-12-31",
}


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'steward-assist.db'}",
            "ACME_SECRET_KEY": "steward-assist-test-secret",
        },
        key_file=tmp_path / "missing.env",
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
    finally:
        factory.dispose()
    return settings


def deliver(settings: Settings, *, record_id: str, payload: dict, version: str = "1") -> None:
    """Deliver one version of a business licence to the source of the City."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            IngestionService(session).ingest(
                IngestCommand(
                    source_system_id="erp_finance",
                    dataset_key="business_licensing_register",
                    records=[
                        SourceRecordCommand(
                            source_record_id=record_id,
                            source_record_version=version,
                            payload=payload,
                            source_updated_at=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
                        )
                    ],
                ),
                STEWARD,
            )
    finally:
        factory.dispose()


def propose(settings: Settings, *, record_id: str) -> str:
    """Ask the registry to compare a source record with the master records."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            view = RegistryService(session).propose(
                MatchProposalCommand(
                    source_system_id="erp_finance",
                    dataset_key="business_licensing_register",
                    source_record_id=record_id,
                ),
                STEWARD,
            )
            return view.proposal_id
    finally:
        factory.dispose()


def recommend(settings: Settings, kind: str, item_id: str) -> steward_assist.Recommendation:
    """Return the recommendation of one task of the queue."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return steward_assist.recommend(session, steward_assist.Task(kind, item_id))
    finally:
        factory.dispose()


def raise_case(settings: Settings, *, proposed: dict, old: dict | None = None) -> str:
    """Raise a correction of a source record and return its identifier."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            view = ChangeService(session).request(
                ChangeRequestCommand(
                    target_type="source_record",
                    target_id="gis/address_register/GIS-AD-0400",
                    title="Fictional correction of an official address",
                    reason="the demonstration corrects a fictional official address",
                    proposed_value=proposed,
                    old_value=old or {},
                ),
                STEWARD,
            )
            return view.change_case_id
    finally:
        factory.dispose()


def add_parcel_match(
    settings: Settings,
    *,
    application_id: str,
    candidates: list[dict],
    parcel_number: str = "",
    link_state: str = "proposed",
) -> str:
    """Record the parcel evidence of an application and return the match id."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            match = gis.ApplicationParcelMatch(
                id=new_id("pmatch"),
                correlation_id=new_id("corr"),
                application_id=application_id,
                submitted_text="400 Lantern Row",
                matched_address="400 Lantern Row" if candidates else None,
                parcel_id=None,
                parcel_number=parcel_number,
                score=max((float(item.get("score") or 0.0) for item in candidates), default=None),
                locator_status="M" if candidates else "U",
                candidates=candidates,
                method="findAddressCandidates + point-in-parcel query",
                link_state=link_state,
                note="a fictional note of the locator",
            )
            session.add(match)
            session.flush()
            return match.id
    finally:
        factory.dispose()


def add_issue(settings: Settings, *, issue_type: str, subject_id: str, queue_id: str = "") -> str:
    """Record a data issue and return its identifier."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            issue = change.GovernanceIssue(
                id=new_id("issue"),
                subject_type="source_record",
                subject_id=subject_id,
                issue_type=issue_type,
                description="a fictional data issue of the demonstration",
                responsible_queue_id=queue_id or None,
                assigned_actor_id=None,
                blocking=False,
                status="open",
            )
            session.add(issue)
            session.flush()
            return issue.id
    finally:
        factory.dispose()


# --------------------------------------------------------------- the record match


def test_a_record_match_that_names_the_master_record_is_high_confidence(seeded: Settings) -> None:
    """A source record that names one master record exactly is ready to accept."""
    proposal_id = propose(seeded, record_id="ERP-BL-00412")
    recommendation = recommend(seeded, "link", proposal_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_HIGH
    assert recommendation.outcome == steward_assist.OUTCOME_CONFIRM
    assert recommendation.evidence["candidate_entity_id"] == "party_cedarline"
    assert recommendation.evidence["score"] == 1.0
    assert set(recommendation.evidence) == LINK_EVIDENCE_KEYS


def test_a_record_match_stores_the_version_of_the_master_record(seeded: Settings) -> None:
    """The recommendation records the version of the record it read."""
    proposal_id = propose(seeded, record_id="ERP-BL-00412")
    recommendation = recommend(seeded, "link", proposal_id)

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            party = session.get(registry.Party, "party_cedarline")
    finally:
        factory.dispose()
    assert recommendation.record_version == party.version


def test_a_record_match_that_lacks_a_second_fact_is_for_review(seeded: Settings) -> None:
    """A match that only one fact supports is prepared, not decided."""
    deliver(seeded, record_id="ERP-BL-00900", payload=UNKNOWN_LICENCE)
    proposal_id = propose(seeded, record_id="ERP-BL-00900")
    recommendation = recommend(seeded, "link", proposal_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_CONFIRM
    assert recommendation.evidence["failed_checks"] == ["corroborating_identity_evidence"]
    assert set(recommendation.evidence) == LINK_EVIDENCE_KEYS


def test_a_record_match_with_a_conflicting_fact_is_held(seeded: Settings) -> None:
    """A licence number the master record does not hold holds the recommendation."""
    deliver(seeded, record_id="ERP-BL-00901", payload=CONFLICTING_LICENCE)
    proposal_id = propose(seeded, record_id="ERP-BL-00901")
    recommendation = recommend(seeded, "link", proposal_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_HELD
    assert recommendation.outcome == steward_assist.OUTCOME_ASK_SOURCE
    assert recommendation.evidence["disagreements"]
    assert set(recommendation.evidence) == LINK_EVIDENCE_KEYS


def test_a_record_match_without_any_candidate_is_rejected(seeded: Settings) -> None:
    """A source record that fits no master record is prepared for a decision."""
    deliver(seeded, record_id="ERP-BL-00902", payload=UNKNOWN_HOLDER)
    proposal_id = propose(seeded, record_id="ERP-BL-00902")
    recommendation = recommend(seeded, "link", proposal_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_REJECT
    assert recommendation.evidence["reasons"] == ["no_candidate"]


def test_the_reason_of_a_match_names_no_identifier(seeded: Settings) -> None:
    """The words the steward read never carry an internal identifier."""
    deliver(seeded, record_id="ERP-BL-00903", payload=CONFLICTING_LICENCE)
    proposal_id = propose(seeded, record_id="ERP-BL-00903")
    recommendation = recommend(seeded, "link", proposal_id)

    assert "party_cedarline" not in recommendation.reason
    assert "ERP-BL-00903" not in recommendation.reason
    assert recommendation.reason.endswith("so a person has to decide.")


def test_a_missing_task_has_no_recommendation(seeded: Settings) -> None:
    """A task whose record is gone is refused."""
    with pytest.raises(NotFoundError):
        recommend(seeded, "link", "proposal_that_does_not_exist")


def test_an_unknown_kind_of_task_has_no_recommendation(seeded: Settings) -> None:
    """The assistant prepares no recommendation for an unknown task."""
    with pytest.raises(ValidationError):
        recommend(seeded, "unknown_task", "anything")


# ------------------------------------------------------------- the applied link


def test_an_applied_link_is_kept_with_high_confidence(seeded: Settings) -> None:
    """A link the policy applied after every check passed may be kept."""
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            seed_automation(session)
    finally:
        factory.dispose()

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = session.execute(
                select(registry_automation.RegistryAutomationApplication)
            ).scalars().one()
    finally:
        factory.dispose()

    recommendation = recommend(seeded, "automatic_link", application.id)
    assert recommendation.confidence == steward_assist.CONFIDENCE_HIGH
    assert recommendation.outcome == steward_assist.OUTCOME_KEEP
    assert recommendation.record_version == application.version
    assert set(recommendation.evidence) == AUTOMATIC_LINK_EVIDENCE_KEYS


def test_an_applied_link_with_a_conflicting_fact_is_held(seeded: Settings) -> None:
    """A link whose recorded evidence disagrees holds the recommendation."""
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            seed_automation(session)
            application = session.execute(
                select(registry_automation.RegistryAutomationApplication)
            ).scalars().one()
            evaluation = session.get(
                registry_automation.RegistryAutomationEvaluation, application.evaluation_id
            )
            evidence = dict(evaluation.evidence or {})
            evidence["conflicting"] = [
                {
                    "field": "license_number",
                    "direction": "conflicting",
                    "method": "credential_number_conflict",
                    "detail": "the master record holds another number",
                }
            ]
            evaluation.evidence = evidence
            session.flush()
            application_id = application.id
    finally:
        factory.dispose()

    recommendation = recommend(seeded, "automatic_link", application_id)
    assert recommendation.confidence == steward_assist.CONFIDENCE_HELD
    assert recommendation.outcome == steward_assist.OUTCOME_UNDO


def test_a_link_that_was_already_reviewed_is_for_review(seeded: Settings) -> None:
    """A link a person already reviewed has nothing left to decide."""
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            seed_automation(session)
            application = session.execute(
                select(registry_automation.RegistryAutomationApplication)
            ).scalars().one()
            automation.acknowledge_application(
                session,
                application_id=application.id,
                note="the steward read the link",
                actor=STEWARD,
            )
            application_id = application.id
    finally:
        factory.dispose()

    recommendation = recommend(seeded, "automatic_link", application_id)
    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_KEEP


# ------------------------------------------------------------------ the property


def test_one_parcel_above_the_line_is_high_confidence(seeded: Settings) -> None:
    """One parcel that fits the address and no other is ready to accept."""
    add_parcel_match(
        seeded,
        application_id="app_synth_001",
        candidates=[{"parcel_number": "ACME-P-1001", "address": "400 Lantern Row", "score": 95.0}],
        parcel_number="ACME-P-1001",
    )
    recommendation = recommend(seeded, "parcel", "app_synth_001")

    assert recommendation.confidence == steward_assist.CONFIDENCE_HIGH
    assert recommendation.outcome == steward_assist.OUTCOME_APPROVE_PARCEL
    assert recommendation.evidence["parcel_number"] == "ACME-P-1001"
    assert set(recommendation.evidence) == PARCEL_EVIDENCE_KEYS


def test_several_parcels_that_fit_equally_are_for_review(seeded: Settings) -> None:
    """Two parcels that fit the address equally leave the choice to the steward."""
    add_parcel_match(
        seeded,
        application_id="app_synth_001",
        candidates=[
            {"parcel_number": "ACME-P-1001", "address": "400 Lantern Row", "score": 95.0},
            {"parcel_number": "ACME-P-1002", "address": "402 Lantern Row", "score": 85.0},
        ],
        parcel_number="ACME-P-1001",
        link_state="needs_choice",
    )
    recommendation = recommend(seeded, "parcel", "app_synth_001")

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_APPROVE_PARCEL
    assert len(recommendation.evidence["candidates"]) == 2


def test_two_parcels_that_score_the_same_are_for_review(seeded: Settings) -> None:
    """Two parcels that score the same leave the choice to the steward."""
    add_parcel_match(
        seeded,
        application_id="app_synth_001",
        candidates=[
            {"parcel_number": "ACME-P-1001", "address": "400 Lantern Row", "score": 95.0},
            {"parcel_number": "ACME-P-1002", "address": "402 Lantern Row", "score": 95.0},
        ],
        parcel_number="ACME-P-1001",
        link_state="needs_choice",
    )
    recommendation = recommend(seeded, "parcel", "app_synth_001")

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_APPROVE_PARCEL


def test_a_parcel_that_contradicts_the_application_is_held(seeded: Settings) -> None:
    """A parcel that is not the one the application names holds the recommendation."""
    add_parcel_match(
        seeded,
        application_id="app_d04",
        candidates=[{"parcel_number": "ACME-P-1001", "address": "400 Lantern Row", "score": 95.0}],
        parcel_number="ACME-P-1001",
    )
    recommendation = recommend(seeded, "parcel", "app_d04")

    assert recommendation.confidence == steward_assist.CONFIDENCE_HELD
    assert recommendation.outcome == steward_assist.OUTCOME_ASK_SOURCE
    assert recommendation.evidence["conflict"]


def test_an_address_that_is_not_found_fits_no_parcel(seeded: Settings) -> None:
    """An address the locator does not know leaves no parcel to approve."""
    add_parcel_match(
        seeded,
        application_id="app_synth_001",
        candidates=[],
        parcel_number="",
        link_state="not_found",
    )
    recommendation = recommend(seeded, "parcel", "app_synth_001")

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_NONE_FITS


def test_a_parcel_link_stores_the_version_of_the_match(seeded: Settings) -> None:
    """The recommendation records the version of the match it read."""
    add_parcel_match(
        seeded,
        application_id="app_synth_001",
        candidates=[{"parcel_number": "ACME-P-1001", "address": "400 Lantern Row", "score": 95.0}],
        parcel_number="ACME-P-1001",
    )
    recommendation = recommend(seeded, "parcel", "app_synth_001")

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            match = session.execute(
                select(gis.ApplicationParcelMatch).where(
                    gis.ApplicationParcelMatch.application_id == "app_synth_001"
                )
            ).scalars().one()
    finally:
        factory.dispose()
    assert recommendation.record_version == match.version


# ----------------------------------------------------------------- the correction


def test_a_correction_the_source_already_holds_is_high_confidence(seeded: Settings) -> None:
    """A correction that matches the value the source holds is ready to accept."""
    case_id = raise_case(seeded, proposed={"postcode": "ACM-01401"})
    recommendation = recommend(seeded, "case", case_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_HIGH
    assert recommendation.outcome == steward_assist.OUTCOME_ACCEPT
    assert recommendation.evidence["current_value"]["postcode"] == "ACM-01401"
    assert set(recommendation.evidence) == CASE_EVIDENCE_KEYS


def test_a_correction_of_a_value_the_source_does_not_hold_is_for_review(seeded: Settings) -> None:
    """A correction the source does not hold yet is prepared, not decided."""
    case_id = raise_case(seeded, proposed={"postcode": "45210"})
    recommendation = recommend(seeded, "case", case_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_ACCEPT


def test_a_correction_of_a_record_that_changed_is_held(seeded: Settings) -> None:
    """A correction raised against another version of the record holds."""
    case_id = raise_case(seeded, proposed={"postcode": "45210"})
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            IngestionService(session).ingest(
                IngestCommand(
                    source_system_id="gis",
                    dataset_key="address_register",
                    records=[
                        SourceRecordCommand(
                            source_record_id="GIS-AD-0400",
                            source_record_version="6",
                            payload={
                                "address_id": "GIS-AD-0400",
                                "street_number": "400",
                                "street_name": "Lantern Row",
                                "street_type": "Row",
                                "municipality": "ACME City",
                                "region": "AC",
                                "postcode": "ACM-01401",
                                "source_string": "400 Lantern Row",
                                "parcel_number": "ACME-P-1001",
                            },
                            source_updated_at=datetime(2026, 10, 30, 13, 0, tzinfo=UTC),
                        )
                    ],
                ),
                STEWARD,
            )
    finally:
        factory.dispose()

    recommendation = recommend(seeded, "case", case_id)
    assert recommendation.confidence == steward_assist.CONFIDENCE_HELD
    assert recommendation.outcome == steward_assist.OUTCOME_ASK_SOURCE
    assert recommendation.evidence["current_version"] == "6"
    assert recommendation.evidence["expected_version"] == 5


def test_a_correction_without_a_value_asks_the_source(seeded: Settings) -> None:
    """A correction that names no value cannot be prepared any further."""
    case_id = raise_case(seeded, proposed={})
    recommendation = recommend(seeded, "case", case_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_ASK_SOURCE


def test_a_correction_stores_the_version_of_the_case(seeded: Settings) -> None:
    """The recommendation records the version of the case it read."""
    case_id = raise_case(seeded, proposed={"postcode": "45210"})
    recommendation = recommend(seeded, "case", case_id)

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            case = session.get(change.ChangeCase, case_id)
    finally:
        factory.dispose()
    assert recommendation.record_version == case.version


# --------------------------------------------------------------------- the issue


def test_a_late_version_issue_can_be_closed(seeded: Settings) -> None:
    """The accepted version stands, so the issue is prepared to be closed."""
    issue_id = add_issue(
        seeded,
        issue_type="late_source_version",
        subject_id="erp_finance:business_licensing_register:ERP-BL-00412",
        queue_id="queue_businesses",
    )
    recommendation = recommend(seeded, "issue", issue_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_HIGH
    assert recommendation.outcome == steward_assist.OUTCOME_RESOLVE
    assert recommendation.evidence["owner"] == "Businesses"
    assert recommendation.evidence["request_draft"]
    assert set(recommendation.evidence) == ISSUE_EVIDENCE_KEYS


def test_a_conflicting_payload_issue_is_held(seeded: Settings) -> None:
    """Two versions that disagree hold the recommendation for a person."""
    issue_id = add_issue(
        seeded,
        issue_type="source_version_payload_conflict",
        subject_id="erp_finance:business_licensing_register:ERP-BL-00412",
        queue_id="queue_businesses",
    )
    recommendation = recommend(seeded, "issue", issue_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_HELD
    assert recommendation.outcome == steward_assist.OUTCOME_AWAITING_SOURCE


def test_an_issue_the_assistant_does_not_know_is_for_review(seeded: Settings) -> None:
    """An issue of an unknown kind is prepared for a person to read."""
    issue_id = add_issue(
        seeded,
        issue_type="a_kind_the_assistant_does_not_know",
        subject_id="erp_finance:business_licensing_register:ERP-BL-00412",
        queue_id="queue_businesses",
    )
    recommendation = recommend(seeded, "issue", issue_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_AWAITING_SOURCE


def test_an_issue_without_an_owner_is_for_review(seeded: Settings) -> None:
    """An issue no queue owns is prepared for a person to place."""
    issue_id = add_issue(
        seeded,
        issue_type="late_source_version",
        subject_id="erp_finance:business_licensing_register:ERP-BL-00412",
    )
    recommendation = recommend(seeded, "issue", issue_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.evidence["owner"] == ""


def test_an_issue_stores_the_version_of_the_issue(seeded: Settings) -> None:
    """The recommendation records the version of the issue it read."""
    issue_id = add_issue(
        seeded,
        issue_type="late_source_version",
        subject_id="erp_finance:business_licensing_register:ERP-BL-00412",
        queue_id="queue_businesses",
    )
    recommendation = recommend(seeded, "issue", issue_id)

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            issue = session.get(change.GovernanceIssue, issue_id)
    finally:
        factory.dispose()
    assert recommendation.record_version == issue.version


# ------------------------------------------------------------------ the recording


def test_a_recorded_recommendation_keeps_what_it_read(seeded: Settings) -> None:
    """The recorded row holds the recommendation and who made it."""
    proposal_id = propose(seeded, record_id="ERP-BL-00412")
    recommendation = recommend(seeded, "link", proposal_id)

    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            row = steward_assist.store_recommendation(session, recommendation)
            session.flush()
            assert row.task_kind == "link"
            assert row.task_id == proposal_id
            assert row.confidence == steward_assist.CONFIDENCE_HIGH
            assert row.outcome == steward_assist.OUTCOME_CONFIRM
            assert row.record_version == recommendation.record_version
            assert row.made_by_actor_id == steward_assist.STEWARD_ASSIST_ACTOR_ID
            assert row.made_at is not None
            assert row.cleared is False
            assert row.cleared_at is None
            assert row.evidence["candidate_entity_id"] == "party_cedarline"
    finally:
        factory.dispose()


def test_a_new_recommendation_clears_the_earlier_one(seeded: Settings) -> None:
    """A task holds one recommendation, so the steward reads one answer."""
    proposal_id = propose(seeded, record_id="ERP-BL-00412")
    recommendation = recommend(seeded, "link", proposal_id)

    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            first = steward_assist.store_recommendation(session, recommendation)
            steward_assist.store_recommendation(session, recommendation)
            session.flush()
            rows = session.execute(
                select(StewardRecommendation).order_by(StewardRecommendation.created_at)
            ).scalars().all()
            assert len(rows) == 2
            assert first.cleared is True
            assert first.cleared_at is not None
            assert rows[-1].cleared is False
    finally:
        factory.dispose()
