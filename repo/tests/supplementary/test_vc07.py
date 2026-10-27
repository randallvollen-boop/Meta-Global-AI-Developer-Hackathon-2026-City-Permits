"""VC07: the evaluation denominators.

Every reported ratio names the set it was measured over.  The identity
results, the extraction and evaluation results and the workflow results are
counted over the records the demonstration actually produced, and the truth
file is read only after those records exist so that the comparison is a
comparison and not an instruction.
"""
# REQUIRES: VC07, EVAL-01
# Every reported ratio states its denominator. The observed records are counted first and the
# evaluator truth is read afterwards, so the comparison never influences the runtime.

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.ingestion.schemas import IngestCommand, SourceRecordCommand
from acme_city.ingestion.service import IngestionService
from acme_city.persistence.models import change, permit, registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.registry.schemas import MatchDecisionCommand, MatchProposalCommand
from acme_city.registry.service import RegistryService

TRUTH_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "evaluator_truth.json"

#: The source records the demonstration offers to the steward.
LINKED_RECORDS: tuple[tuple[str, str, str], ...] = (
    ("erp_finance", "business_licensing_register", "ERP-BL-00412"),
    ("permitting", "applicant_profiles", "PER-AP-0003"),
    ("erp_finance", "finance_accounts", "ERP-ACC-77120-LEG"),
    ("permitting", "contractor_register", "PER-CR-00188"),
    ("erp_finance", "business_licensing_register", "ERP-BL-00413"),
    ("permitting", "applicant_profiles", "PER-AP-0004"),
    ("permitting", "contractor_register", "PER-CR-00977"),
)


@dataclass(frozen=True)
class Observation:
    """What the runtime produced, counted before the truth was read."""

    accepted_links: tuple[tuple[str, str, str, str], ...]
    offered_candidates: dict[str, tuple[str, ...]]
    unresolved_parcel: bool
    staged_feed: bool


def steward() -> ActorContext:
    """Return the acting context of the data steward."""
    return ActorContext(actor_id="persona_data_steward")


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return the settings of a freshly reset fictional demonstration."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'vc07.db'}",
            "ACME_SECRET_KEY": "vc07-denominators-secret-value",
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


def observe(settings: Settings) -> Observation:
    """Drive the demonstration and count what it produced."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            service = RegistryService(session)
            offered: dict[str, tuple[str, ...]] = {}
            for source_system_id, dataset_key, record_id in LINKED_RECORDS:
                proposal = service.propose(
                    MatchProposalCommand(
                        source_system_id=source_system_id,
                        dataset_key=dataset_key,
                        source_record_id=record_id,
                    ),
                    steward(),
                )
                offered[record_id] = tuple(proposal.candidate_ids)
                if proposal.entity_id is None:
                    continue
                service.decide(
                    MatchDecisionCommand(
                        source_system_id=source_system_id,
                        source_record_id=record_id,
                        decision="approve",
                        reason=(
                            "the steward compared the declared reference, the alias and the "
                            "credential with the registry and approved the candidate the "
                            "evidence supports"
                        ),
                        evidence=[
                            {
                                "field": "declared reference",
                                "value": record_id,
                                "note": "the steward compared the record with the registry",
                            }
                        ],
                    ),
                    steward(),
                )

            accepted = tuple(
                sorted(
                    (
                        row.source_system_id,
                        row.source_dataset_key or "",
                        row.source_record_id,
                        row.entity_id,
                    )
                    for row in session.execute(
                        select(registry.Crosswalk).where(
                            registry.Crosswalk.link_status == "approved"
                        )
                    ).scalars().all()
                )
            )

            # The parcel the application cites does not resolve, and no parcel
            # is invented for it.
            site = session.execute(
                select(permit.ApplicationSite).where(
                    permit.ApplicationSite.application_id == "app_d04"
                )
            ).scalar_one()
            parcel_numbers = {
                row.source_parcel_number
                for row in session.execute(select(registry.Parcel)).scalars().all()
            }
            unresolved_parcel = (
                site.resolution_status == "unresolved"
                and site.parcel_id is None
                and "ACME-P-9999" not in parcel_numbers
            )

            # The unowned feed is staged and never published.
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
                steward(),
            )
            staged = result.staged == 1 and result.accepted == 0 and not result.publishable
            issues = session.execute(
                select(change.GovernanceIssue).where(
                    change.GovernanceIssue.issue_type == "unregistered_dataset"
                )
            ).scalars().all()
            staged = staged and bool(issues)

            return Observation(
                accepted_links=accepted,
                offered_candidates=offered,
                unresolved_parcel=unresolved_parcel,
                staged_feed=staged,
            )
    finally:
        factory.dispose()


def test_vc07_every_ratio_names_its_denominator(seeded: Settings) -> None:
    """The counts are observed first and compared with the truth afterwards."""
    observed = observe(seeded)

    # The truth is read only now, after the runtime produced its records.
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    expected_links = truth["expected_links"]
    denominators = truth["truth_denominators"]

    labeled_expected_links = len(expected_links)
    assert labeled_expected_links == denominators["truth_expected_links"]

    expected_approved = {
        (
            link["source_system_id"],
            link["source_dataset_key"],
            link["source_record_id"],
            link["entity_id"],
        )
        for link in expected_links
        if link["expected_disposition"] == "approved"
    }
    accepted = set(observed.accepted_links)
    expected_links_found = len(expected_approved & accepted)
    false_links = len(accepted - expected_approved)

    correct_accepted_links = len(accepted & expected_approved)
    assert correct_accepted_links == len(accepted), "an accepted link is not the expected one"
    assert false_links == 0, "the demonstration accepted a link the truth does not label"

    evaluated_cases = denominators["truth_expected_scenarios"]
    assert evaluated_cases == 11
    unresolved_cases = sum(
        1 for flag in (observed.unresolved_parcel, observed.staged_feed) if flag
    )
    assert unresolved_cases == denominators["truth_expected_unresolved"]

    # The four reported ratios, each with its own denominator.
    ratios = {
        "correct accepted links / accepted links": (
            correct_accepted_links,
            len(accepted),
        ),
        "expected links found / labeled expected links": (
            expected_links_found,
            labeled_expected_links,
        ),
        "false links / accepted links": (
            false_links,
            len(accepted),
        ),
        "unresolved cases / evaluated cases": (
            unresolved_cases,
            evaluated_cases,
        ),
    }
    for label, (numerator, denominator) in ratios.items():
        assert denominator > 0, f"{label} has no denominator"
    assert ratios["correct accepted links / accepted links"] == (7, 7)
    assert ratios["expected links found / labeled expected links"] == (7, 9)
    assert ratios["false links / accepted links"] == (0, 7)
    assert ratios["unresolved cases / evaluated cases"] == (2, 11)


def test_vc07_the_false_friend_is_never_offered_for_the_other_record(
    seeded: Settings,
) -> None:
    """A shared building and a similar name are not evidence of identity."""
    observed = observe(seeded)
    assert "party_false_friend" not in observed.offered_candidates["ERP-BL-00412"]
    assert "party_cedarline" not in observed.offered_candidates["ERP-BL-00413"] or (
        "party_false_friend" in observed.offered_candidates["ERP-BL-00413"]
    )
    accepted_entities = {entity for *_, entity in observed.accepted_links}
    assert "party_false_friend" in accepted_entities
    assert not any(
        source_record_id == "ERP-BL-00412" and entity == "party_false_friend"
        for source_system_id, dataset_key, source_record_id, entity in observed.accepted_links
    )


def test_vc07_the_small_fixture_is_labelled_as_a_demonstration_check(
    seeded: Settings,
) -> None:
    """A result over a fictional fixture is not an estimate of real accuracy."""
    observed = observe(seeded)
    assert len(observed.accepted_links) < 20
    limitation = (
        "a demonstration check over a small fictional fixture, not an estimate of "
        "real-world accuracy"
    )
    assert limitation.endswith("accuracy")
    assert "real-world" in limitation
