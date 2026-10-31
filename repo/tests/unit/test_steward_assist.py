"""The deterministic recommendations of the steward assistant.

Every kind of task of the queue is covered: the recommendation names what the
assistant proposes, how sure it is, the evidence it read and the version of
the record it read.  The recommendation never decides anything: the steward
does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from acme_city.gis.adapter import LocatorCandidate, ParcelRecord
from acme_city.gis.matching import ParcelMatchService
from acme_city.ingestion.schemas import IngestCommand, SourceRecordCommand
from acme_city.ingestion.service import IngestionService
from acme_city.persistence.models import change, gis, permit, registry, registry_automation
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.registry import automation, steward_assist
from acme_city.registry.schemas import MatchDecisionCommand, MatchProposalCommand
from acme_city.registry.service import RegistryService

STEWARD = ActorContext(actor_id="persona_data_steward", role_ids=frozenset({"domain_steward"}))

#: The keys of the evidence of every kind of task.
LINK_EVIDENCE_KEYS = {
    "source_system",
    "source_dataset",
    "source_record_id",
    "source_snapshot_id",
    "source_version",
    "candidate_entity_id",
    "candidate_label",
    "candidate_version",
    "score",
    "next_best_score",
    "auto_apply_threshold",
    "suggest_threshold",
    "policy_decision",
    "reasons",
    "failed_checks",
    "version_token",
    "crosswalk_id",
    "crosswalk_version",
    "agreements",
    "disagreements",
}

AUTOMATIC_LINK_EVIDENCE_KEYS = {
    "application_id",
    "crosswalk_id",
    "crosswalk_version",
    "entity_id",
    "entity_label",
    "entity_version",
    "source_system",
    "source_dataset",
    "source_record_id",
    "source_snapshot_id",
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
    "address_id",
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


def recommend(
    settings: Settings,
    kind: str,
    item_id: str,
    *,
    app_settings: Settings | None = None,
) -> steward_assist.Recommendation:
    """Return the recommendation of one task of the queue."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return steward_assist.recommend(
                session,
                steward_assist.Task(kind, item_id),
                settings=app_settings or settings,
            )
    finally:
        factory.dispose()


#: The candidates the fictional locator of the tests answers with.
LANTERN_CANDIDATES: tuple[LocatorCandidate, ...] = (
    LocatorCandidate(
        address="400 Lantern Row",
        x=100.0,
        y=200.0,
        score=95.0,
        status="M",
        address_id="GIS-AD-0400",
    ),
    LocatorCandidate(
        address="402 Lantern Row",
        x=300.0,
        y=400.0,
        score=70.0,
        status="M",
        address_id="GIS-AD-0401",
    ),
)

#: The parcels the fictional locator of the tests answers with.
LANTERN_PARCELS: dict[tuple[float, float], ParcelRecord] = {
    (100.0, 200.0): ParcelRecord(parcel_number="ACME-P-1001", site_address="400 Lantern Row"),
    (300.0, 400.0): ParcelRecord(parcel_number="ACME-P-1002", site_address="402 Lantern Row"),
}


class FictionalLocator:
    """A locator that answers with the fictional parcels of the demonstration."""

    def __init__(
        self,
        candidates: tuple[LocatorCandidate, ...],
        parcels: dict[tuple[float, float], ParcelRecord],
    ) -> None:
        self._candidates = candidates
        self._parcels = parcels

    @property
    def source_label(self) -> str:
        return "ACME GIS (fictional locator of the test)"

    def find_candidates(self, text: str, max_locations: int = 5) -> list[LocatorCandidate]:
        return list(self._candidates[:max_locations])

    def suggest(self, text: str, limit: int = 5) -> list[dict[str, str]]:
        return []

    def candidate_for_key(self, magic_key: str) -> LocatorCandidate | None:
        return None

    def reverse_geocode(self, x: float, y: float) -> LocatorCandidate | None:
        return None

    def parcel_at(self, x: float, y: float) -> ParcelRecord | None:
        return self._parcels.get((float(x), float(y)))

    def parcel_by_number(self, parcel_number: str) -> ParcelRecord | None:
        return next(
            (
                parcel
                for parcel in self._parcels.values()
                if parcel.parcel_number == parcel_number
            ),
            None,
        )

    def addresses_on_parcel(self, parcel_number: str) -> list[object]:
        return []


def locate(
    settings: Settings,
    *,
    application_id: str = "app_synth_001",
    candidates: tuple[LocatorCandidate, ...] = LANTERN_CANDIDATES,
    parcels: dict[tuple[float, float], ParcelRecord] | None = None,
    app_settings: Settings | None = None,
) -> None:
    """Run the address locator of the City for one application."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(permit.Application, application_id)
            assert application is not None
            service = ParcelMatchService(
                session,
                settings=app_settings or settings,
                locator=FictionalLocator(
                    candidates, LANTERN_PARCELS if parcels is None else parcels
                ),
            )
            service.locate(application, STEWARD)
    finally:
        factory.dispose()


def choose_candidate(
    settings: Settings,
    *,
    application_id: str = "app_synth_001",
    address_id: str,
    candidates: tuple[LocatorCandidate, ...] = LANTERN_CANDIDATES,
    parcels: dict[tuple[float, float], ParcelRecord] | None = None,
) -> None:
    """Let the steward propose another candidate of the locator."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            service = ParcelMatchService(
                session,
                settings=settings,
                locator=FictionalLocator(
                    candidates, LANTERN_PARCELS if parcels is None else parcels
                ),
            )
            service.choose_candidate(
                application_id,
                address_id=address_id,
                reason="the fictional steward proposes another candidate",
                expected_version=None,
                actor=STEWARD,
            )
    finally:
        factory.dispose()


def find_by_number(
    settings: Settings,
    *,
    application_id: str = "app_synth_001",
    parcel_number: str = "ACME-P-1002",
    candidates: tuple[LocatorCandidate, ...] = LANTERN_CANDIDATES,
    parcels: dict[tuple[float, float], ParcelRecord] | None = None,
) -> None:
    """Let the steward look a parcel up in the parcel layer by its number."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            service = ParcelMatchService(
                session,
                settings=settings,
                locator=FictionalLocator(
                    candidates, LANTERN_PARCELS if parcels is None else parcels
                ),
            )
            service.find_by_number(
                application_id,
                parcel_number=parcel_number,
                reason="the fictional steward looks the parcel up by its number",
                expected_version=None,
                actor=STEWARD,
            )
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


def deliver_address_without_a_value(settings: Settings) -> None:
    """Deliver a newer version of the official address with an empty field."""
    factory = SessionFactory(settings.database_url)
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
                                "street_type": None,
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


def add_issue(
    settings: Settings,
    *,
    issue_type: str,
    subject_id: str,
    queue_id: str = "",
    subject_type: str = "source_record",
) -> str:
    """Record a data issue and return its identifier."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            issue = change.GovernanceIssue(
                id=new_id("issue"),
                subject_type=subject_type,
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


def test_a_record_match_stores_the_version_of_the_link(seeded: Settings) -> None:
    """The recommendation records the version of the link it is decided on.

    The steward decides on the link, and the service of the City compares the
    version of that link, so the recommendation has to carry it.  The master
    record has a version of its own, and it is not the one.
    """
    proposal_id = propose(seeded, record_id="ERP-BL-00412")
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            party = session.get(registry.Party, "party_cedarline")
            assert party is not None
            party.version += 1
            master_version = party.version
    finally:
        factory.dispose()

    recommendation = recommend(seeded, "link", proposal_id)

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            crosswalk = RegistryService(session).open_crosswalk(
                "erp_finance", "ERP-BL-00412"
            )
    finally:
        factory.dispose()
    assert crosswalk is not None
    assert recommendation.record_version == crosswalk.version
    assert recommendation.record_version != master_version
    assert recommendation.evidence["crosswalk_id"] == crosswalk.id
    assert recommendation.evidence["crosswalk_version"] == crosswalk.version
    assert recommendation.evidence["version_token"] == steward_assist.VERSION_TOKEN_CROSSWALK
    # The master record and the source version travel with it as evidence.
    assert recommendation.evidence["candidate_entity_id"] == "party_cedarline"
    assert recommendation.evidence["candidate_version"] == master_version
    assert recommendation.evidence["source_snapshot_id"]


def test_a_record_match_without_a_candidate_names_the_source_it_read(
    seeded: Settings,
) -> None:
    """A task without a link depends on the version of the source record."""
    deliver(seeded, record_id="ERP-BL-00902", payload=UNKNOWN_HOLDER)
    proposal_id = propose(seeded, record_id="ERP-BL-00902")
    recommendation = recommend(seeded, "link", proposal_id)

    assert recommendation.evidence["version_token"] == (
        steward_assist.VERSION_TOKEN_CURRENT_SOURCE
    )
    assert recommendation.evidence["crosswalk_id"] == ""
    assert recommendation.evidence["source_snapshot_id"]


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


def add_twin_party(settings: Settings) -> None:
    """Record a second master record with the name and licence of the other one."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                registry.CanonicalEntity(
                    id="party_cedarline_twin",
                    entity_id="party_cedarline_twin",
                    entity_type="party",
                    label="Cedarline Coffee Roasters LLC",
                    status="active",
                )
            )
            session.add(
                registry.Party(
                    id="party_cedarline_twin",
                    entity_id="party_cedarline_twin",
                    party_type="organization",
                    display_name="Cedarline Coffee Roasters LLC",
                    legal_name="Cedarline Coffee Roasters LLC",
                    status="active",
                )
            )
            session.flush()
            session.add(
                registry.Credential(
                    id="cred_license_cedarline_twin",
                    credential_id="cred_license_cedarline_twin",
                    holder_party_id="party_cedarline_twin",
                    credential_type="business_license",
                    issuing_authority_id="erp_finance:business_licensing_register",
                    number="BL-2026-00412",
                    status="active",
                    valid_from=datetime(2026, 1, 15, tzinfo=UTC),
                    valid_to=datetime(2026, 12, 31, tzinfo=UTC),
                    verified_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
                    source_system_id="erp_finance",
                    source_record_id="ERP-BL-00904",
                )
            )
    finally:
        factory.dispose()


def test_a_close_second_master_record_is_explained(seeded: Settings) -> None:
    """A master record that fits almost as well is named in the reason."""
    add_twin_party(seeded)
    deliver(
        seeded,
        record_id="ERP-BL-00904",
        payload={
            "holder_name": "Cedarline Coffee Roasters",
            "license_number": "BL-2026-00412",
            "status": "active",
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
        },
    )
    proposal_id = propose(seeded, record_id="ERP-BL-00904")
    recommendation = recommend(seeded, "link", proposal_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert "another master record fits almost as well" in recommendation.reason
    assert "party_score_gap" in recommendation.evidence["reasons"]
    assert recommendation.evidence["next_best_score"] == recommendation.evidence["score"]


def test_a_missing_task_has_no_recommendation(seeded: Settings) -> None:
    """A task whose record is gone is refused."""
    with pytest.raises(NotFoundError):
        recommend(seeded, "link", "proposal_that_does_not_exist")


def test_an_unknown_kind_of_task_has_no_recommendation(seeded: Settings) -> None:
    """The assistant prepares no recommendation for an unknown task."""
    with pytest.raises(ValidationError):
        recommend(seeded, "unknown_task", "anything")


def test_the_supported_kinds_are_the_kinds_the_assistant_prepares() -> None:
    """The kinds the screens offer and the dispatch never contradict each other."""
    # The dispatch of the assistant is the one list of kinds; nothing else
    # declares them.
    assert steward_assist.TASK_KINDS == tuple(steward_assist._BUILDERS)
    assert set(steward_assist.TASK_KINDS) == {
        "link",
        "automatic_link",
        "parcel",
        "case",
        "issue",
    }


def test_the_words_of_the_assistant_name_no_check_it_always_passes() -> None:
    """The assistant never fails these two checks, so it has no words for them."""
    always_passed = {"undo_supported", "permissions_granted"}
    assert always_passed.isdisjoint(steward_assist.CHECK_WORDS)


def applied_link(settings: Settings) -> str:
    """Run the automatic linking demonstration and return the applied link."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            seed_automation(session)
            application = session.execute(
                select(registry_automation.RegistryAutomationApplication)
            ).scalars().one()
            return application.id
    finally:
        factory.dispose()


def deliver_newer_applicant(settings: Settings) -> None:
    """Deliver a newer version of the applicant record of the demonstration."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            IngestionService(session).ingest(
                IngestCommand(
                    source_system_id="permitting",
                    dataset_key="applicant_profiles",
                    records=[
                        SourceRecordCommand(
                            source_record_id="PER-AP-0001",
                            source_record_version="4",
                            payload={
                                "party_ref": "party_cedarline",
                                "display_name": "Demo Applicant",
                                "contact_email": "demo.applicant@example.invalid",
                                "contact_phone": "+1-555-0141",
                                "preferred_contact": "email",
                            },
                            source_updated_at=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
                        )
                    ],
                ),
                STEWARD,
            )
    finally:
        factory.dispose()


def recorded_evidence(settings: Settings, application_id: str, **changes: Any) -> None:
    """Change the evidence the policy recorded for an applied link."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(
                registry_automation.RegistryAutomationApplication, application_id
            )
            assert application is not None
            evaluation = session.get(
                registry_automation.RegistryAutomationEvaluation, application.evaluation_id
            )
            assert evaluation is not None
            evidence = dict(evaluation.evidence or {})
            evidence.update(changes)
            evaluation.evidence = evidence
    finally:
        factory.dispose()


def take_the_link_back(settings: Settings, application_id: str) -> None:
    """Let a person take the applied link back."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(
                registry_automation.RegistryAutomationApplication, application_id
            )
            assert application is not None
            crosswalk = session.get(registry.Crosswalk, application.crosswalk_id)
            assert crosswalk is not None
            RegistryService(session).decide(
                MatchDecisionCommand(
                    decision="remove",
                    reason="the fictional steward takes the link back",
                    source_system_id=crosswalk.source_system_id,
                    dataset_key=crosswalk.source_dataset_key,
                    source_record_id=crosswalk.source_record_id,
                    crosswalk_id=crosswalk.id,
                    expected_version=crosswalk.version,
                ),
                STEWARD,
            )
    finally:
        factory.dispose()


def approve_the_link_again(settings: Settings, application_id: str) -> None:
    """Let a person approve the applied link again, with the same target."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(
                registry_automation.RegistryAutomationApplication, application_id
            )
            assert application is not None
            crosswalk = session.get(registry.Crosswalk, application.crosswalk_id)
            assert crosswalk is not None
            RegistryService(session).decide(
                MatchDecisionCommand(
                    decision="approve",
                    reason="the fictional steward approves the link again",
                    source_system_id=crosswalk.source_system_id,
                    dataset_key=crosswalk.source_dataset_key,
                    source_record_id=crosswalk.source_record_id,
                    crosswalk_id=crosswalk.id,
                    expected_version=crosswalk.version,
                ),
                STEWARD,
            )
    finally:
        factory.dispose()


def blank_the_recorded_evidence(settings: Settings, application_id: str) -> None:
    """Take the recorded evidence of an applied link away."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(
                registry_automation.RegistryAutomationApplication, application_id
            )
            assert application is not None
            evaluation = session.get(
                registry_automation.RegistryAutomationEvaluation, application.evaluation_id
            )
            assert evaluation is not None
            evaluation.evidence = {}
    finally:
        factory.dispose()


# ------------------------------------------------------------- the applied link


def test_an_applied_link_is_kept_with_high_confidence(seeded: Settings) -> None:
    """A link the policy applied after every check passed may be kept."""
    application_id = applied_link(seeded)

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = session.get(
                registry_automation.RegistryAutomationApplication, application_id
            )
            party = session.get(registry.Party, "party_applicant_1")
            party_version = int(party.version) if party is not None else 0
    finally:
        factory.dispose()

    recommendation = recommend(seeded, "automatic_link", application_id)
    assert recommendation.confidence == steward_assist.CONFIDENCE_HIGH
    assert recommendation.outcome == steward_assist.OUTCOME_KEEP
    assert recommendation.record_version == application.version
    assert recommendation.evidence["entity_id"] == "party_applicant_1"
    assert recommendation.evidence["entity_version"] == party_version
    assert set(recommendation.evidence) == AUTOMATIC_LINK_EVIDENCE_KEYS


def test_an_applied_link_with_a_newer_source_version_is_held(seeded: Settings) -> None:
    """A source record that changed since the link was applied holds the link."""
    application_id = applied_link(seeded)
    deliver_newer_applicant(seeded)

    recommendation = recommend(seeded, "automatic_link", application_id)
    assert recommendation.confidence == steward_assist.CONFIDENCE_HELD
    assert recommendation.outcome == steward_assist.OUTCOME_UNDO
    assert "source record changed" in recommendation.reason


def test_an_applied_link_a_person_changed_is_held(seeded: Settings) -> None:
    """A link a person took back since it was applied holds the link."""
    application_id = applied_link(seeded)
    take_the_link_back(seeded, application_id)

    recommendation = recommend(seeded, "automatic_link", application_id)
    assert recommendation.confidence == steward_assist.CONFIDENCE_HELD
    assert recommendation.outcome == steward_assist.OUTCOME_UNDO
    assert "link changed" in recommendation.reason


def test_an_applied_link_whose_recorded_check_failed_is_held(seeded: Settings) -> None:
    """A link the policy applied without every check is held for a person."""
    application_id = applied_link(seeded)
    recorded_evidence(seeded, application_id, failed_checks=["no_identity_conflict"])

    recommendation = recommend(seeded, "automatic_link", application_id)
    assert recommendation.confidence == steward_assist.CONFIDENCE_HELD
    assert recommendation.outcome == steward_assist.OUTCOME_UNDO


def test_an_applied_link_without_its_evidence_is_for_review(seeded: Settings) -> None:
    """A link whose evidence is gone is left to a person."""
    application_id = applied_link(seeded)
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(
                registry_automation.RegistryAutomationApplication, application_id
            )
            assert application is not None
            evaluation = session.get(
                registry_automation.RegistryAutomationEvaluation, application.evaluation_id
            )
            assert evaluation is not None
            evaluation.score = None
    finally:
        factory.dispose()

    recommendation = recommend(seeded, "automatic_link", application_id)
    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_KEEP


def test_an_applied_link_whose_recorded_evidence_is_incomplete_is_for_review(
    seeded: Settings,
) -> None:
    """A link whose recorded evaluation is not a complete success is left to a person."""
    application_id = applied_link(seeded)
    blank_the_recorded_evidence(seeded, application_id)

    recommendation = recommend(seeded, "automatic_link", application_id)
    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_KEEP
    assert "incomplete" in recommendation.reason


def change_the_recorded_evidence(
    settings: Settings, application_id: str, part: str, value: object
) -> None:
    """Replace one part of the recorded evidence of an applied link (``...`` removes it)."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(
                registry_automation.RegistryAutomationApplication, application_id
            )
            assert application is not None
            evaluation = session.get(
                registry_automation.RegistryAutomationEvaluation, application.evaluation_id
            )
            assert evaluation is not None
            evidence = dict(evaluation.evidence or {})
            assert part in evidence
            if value is ...:
                del evidence[part]
            else:
                evidence[part] = value
            evaluation.evidence = evidence
    finally:
        factory.dispose()


@pytest.mark.parametrize(
    ("part", "value"),
    [
        ("failed_checks", None),
        ("conflicting", None),
        ("reasons", ...),
    ],
)
def test_an_applied_link_whose_recorded_check_results_are_unreadable_is_for_review(
    seeded: Settings, part: str, value: object
) -> None:
    """A null list of failures, or no recorded explanation, is no success."""
    application_id = applied_link(seeded)
    change_the_recorded_evidence(seeded, application_id, part, value)

    recommendation = recommend(seeded, "automatic_link", application_id)
    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_KEEP
    assert "incomplete" in recommendation.reason


def test_an_applied_link_a_person_approved_again_is_for_review(seeded: Settings) -> None:
    """A link a person decided after the automation applied it is left to that person."""
    application_id = applied_link(seeded)
    approve_the_link_again(seeded, application_id)

    recommendation = recommend(seeded, "automatic_link", application_id)
    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_KEEP
    assert "person decided" in recommendation.reason


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
    locate(
        seeded,
        candidates=(LANTERN_CANDIDATES[0],),
        parcels={(100.0, 200.0): LANTERN_PARCELS[(100.0, 200.0)]},
    )
    recommendation = recommend(seeded, "parcel", "app_synth_001")

    assert recommendation.confidence == steward_assist.CONFIDENCE_HIGH
    assert recommendation.outcome == steward_assist.OUTCOME_APPROVE_PARCEL
    assert recommendation.evidence["parcel_number"] == "ACME-P-1001"
    assert recommendation.evidence["parcel_id"] == "parcel_1001"
    assert recommendation.evidence["score"] == 95.0
    assert recommendation.evidence["link_state"] == "proposed"
    assert set(recommendation.evidence) == PARCEL_EVIDENCE_KEYS


def test_an_address_point_in_no_parcel_is_for_review(seeded: Settings) -> None:
    """A point that falls in no parcel leaves the parcel to a person."""
    locate(seeded, candidates=(LANTERN_CANDIDATES[0],), parcels={})
    recommendation = recommend(seeded, "parcel", "app_synth_001")

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_NONE_FITS
    assert "does not fall inside" in recommendation.reason
    assert recommendation.evidence["parcel_id"] == ""


def test_the_line_the_city_configures_decides(seeded: Settings) -> None:
    """A parcel below the line the City configured is not ready to accept."""
    locate(
        seeded,
        candidates=(LANTERN_CANDIDATES[0],),
        parcels={(100.0, 200.0): LANTERN_PARCELS[(100.0, 200.0)]},
    )
    strict = seeded.model_copy(update={"gis_auto_propose_score": 98})
    recommendation = recommend(seeded, "parcel", "app_synth_001", app_settings=strict)

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.evidence["auto_apply_threshold"] == 98


def test_the_score_of_the_selected_parcel_decides(seeded: Settings) -> None:
    """The score that counts is the score of the parcel that is proposed."""
    locate(
        seeded,
        application_id="app_d05",
        candidates=LANTERN_CANDIDATES,
        parcels=LANTERN_PARCELS,
    )
    choose_candidate(seeded, application_id="app_d05", address_id="GIS-AD-0401")
    recommendation = recommend(seeded, "parcel", "app_d05")

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.evidence["score"] == 70.0
    assert recommendation.evidence["parcel_number"] == "ACME-P-1002"
    assert recommendation.evidence["address_id"] == "GIS-AD-0401"
    chosen = [
        item for item in recommendation.evidence["candidates"] if item["selected"]
    ]
    assert len(chosen) == 1
    assert chosen[0]["parcel_number"] == "ACME-P-1002"


def test_a_parcel_found_by_its_number_is_the_one_proposed(seeded: Settings) -> None:
    """A parcel the steward looked up by number is proposed, not written off."""
    locate(seeded, application_id="app_d05", candidates=(), parcels=LANTERN_PARCELS)
    find_by_number(seeded, application_id="app_d05", parcel_number="ACME-P-1002")
    recommendation = recommend(seeded, "parcel", "app_d05")

    assert recommendation.outcome == steward_assist.OUTCOME_APPROVE_PARCEL
    assert recommendation.evidence["parcel_number"] == "ACME-P-1002"
    assert recommendation.evidence["parcel_id"] == "parcel_1002"
    assert recommendation.evidence["score"] == 100.0


def test_several_parcels_that_fit_equally_are_for_review(seeded: Settings) -> None:
    """Another parcel that fits the address nearly as well leaves the choice to the steward."""
    runner_up = (
        LocatorCandidate(
            address="400 Lantern Row",
            x=100.0,
            y=200.0,
            score=95.0,
            status="M",
            address_id="GIS-AD-0400",
        ),
        LocatorCandidate(
            address="402 Lantern Row",
            x=300.0,
            y=400.0,
            score=85.0,
            status="M",
            address_id="GIS-AD-0401",
        ),
    )
    locate(seeded, candidates=runner_up, parcels=LANTERN_PARCELS)
    recommendation = recommend(seeded, "parcel", "app_synth_001")

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_APPROVE_PARCEL
    assert "Several parcels fit" in recommendation.reason
    assert recommendation.evidence["score"] == 95.0
    assert len(recommendation.evidence["candidates"]) == 2


def test_two_parcels_that_fit_the_address_equally_are_for_review(
    seeded: Settings,
) -> None:
    """Two parcels that fit the address equally leave the choice to the steward."""
    tied = (
        LocatorCandidate(
            address="400 Lantern Row",
            x=100.0,
            y=200.0,
            score=95.0,
            status="M",
            address_id="GIS-AD-0400",
        ),
        LocatorCandidate(
            address="402 Lantern Row",
            x=300.0,
            y=400.0,
            score=95.0,
            status="M",
            address_id="GIS-AD-0401",
        ),
    )
    locate(seeded, candidates=tied, parcels=LANTERN_PARCELS)
    recommendation = recommend(seeded, "parcel", "app_synth_001")

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_APPROVE_PARCEL
    assert "Several parcels fit" in recommendation.reason
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
    locate(
        seeded,
        candidates=(LANTERN_CANDIDATES[0],),
        parcels={(100.0, 200.0): LANTERN_PARCELS[(100.0, 200.0)]},
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


def test_a_correction_of_a_field_the_source_does_not_hold_is_for_review(
    seeded: Settings,
) -> None:
    """A field the source does not hold cannot be certified as matching."""
    case_id = raise_case(seeded, proposed={"does_not_exist": ""})
    recommendation = recommend(seeded, "case", case_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_ACCEPT
    assert "does not name this field" in recommendation.reason


def test_a_correction_of_a_number_the_source_holds_as_text_is_for_review(
    seeded: Settings,
) -> None:
    """A number is not the text of that number."""
    case_id = raise_case(seeded, proposed={"street_number": 400})
    recommendation = recommend(seeded, "case", case_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_ACCEPT


def test_a_correction_of_an_empty_value_is_for_review(seeded: Settings) -> None:
    """An empty value of the source is not the text of it."""
    deliver_address_without_a_value(seeded)
    case_id = raise_case(seeded, proposed={"street_type": "None"})
    recommendation = recommend(seeded, "case", case_id)

    assert recommendation.confidence == steward_assist.CONFIDENCE_REVIEW
    assert recommendation.outcome == steward_assist.OUTCOME_ACCEPT
    assert recommendation.evidence["current_value"]["street_type"] is None


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


def test_a_drafted_request_names_no_internal_identifier(seeded: Settings) -> None:
    """The draft the steward sends names the record, not the machinery."""
    issue_id = add_issue(
        seeded,
        issue_type="unresolved_field_authority",
        subject_id="party_cedarline:postal_address",
        subject_type="canonical_entity",
        queue_id="queue_businesses",
    )
    recommendation = recommend(seeded, "issue", issue_id)

    draft = recommendation.evidence["request_draft"]
    assert "party_cedarline" not in draft
    assert "postal_address" not in draft
    assert "Cedarline Coffee Roasters LLC" in draft
    assert "postal address" in draft


def test_a_drafted_request_of_an_unmatched_record_names_no_identifier(
    seeded: Settings,
) -> None:
    """The draft of a record the registry does not hold names no identifier."""
    issue_id = add_issue(
        seeded,
        issue_type="unresolved_field_authority",
        subject_id="party_missing:postal_address",
        subject_type="canonical_entity",
        queue_id="queue_businesses",
    )
    recommendation = recommend(seeded, "issue", issue_id)

    draft = recommendation.evidence["request_draft"]
    assert "party_missing" not in draft
    assert "party_missing:postal_address" not in draft
    assert "a record the City has not matched yet" in draft
    assert recommendation.evidence["subject_id"] == "party_missing:postal_address"


def test_a_drafted_request_of_an_unknown_subject_names_no_identifier(
    seeded: Settings,
) -> None:
    """The draft of a subject of an unknown kind names no identifier."""
    issue_id = add_issue(
        seeded,
        issue_type="unresolved_field_authority",
        subject_id="party_missing:postal_address",
        subject_type="a_kind_the_assistant_does_not_know",
        queue_id="queue_businesses",
    )
    recommendation = recommend(seeded, "issue", issue_id)

    draft = recommendation.evidence["request_draft"]
    assert "party_missing" not in draft
    assert "party_missing:postal_address" not in draft
    assert "a record the City could not identify" in draft
    assert recommendation.evidence["subject_id"] == "party_missing:postal_address"


def test_a_drafted_request_names_the_registered_dataset(seeded: Settings) -> None:
    """The draft the steward sends names the dataset the City registered."""
    issue_id = add_issue(
        seeded,
        issue_type="unregistered_dataset",
        subject_id="business_licensing_register",
        subject_type="source_dataset",
        queue_id="queue_businesses",
    )
    recommendation = recommend(seeded, "issue", issue_id)

    draft = recommendation.evidence["request_draft"]
    assert "business_licensing_register" not in draft
    assert "Business licences" in draft


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
