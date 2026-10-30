"""The rules of the batch the Data Steward may accept.

A batch accepts what the assistant is sure of and what the steward can take
back: a link of a family whose reversal the City has tested.  A data issue
has no service action, a parcel link and a correction are not reversed by an
action of the City, and a family without a tested reversal is only ever
suggested to a person.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.registry import steward_assist
from acme_city.registry.schemas import MatchProposalCommand
from acme_city.registry.service import RegistryService

STEWARD = ActorContext(actor_id="persona_data_steward", role_ids=frozenset({"domain_steward"}))


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'steward-batch.db'}",
            "ACME_SECRET_KEY": "steward-batch-test-secret",
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


def recommendation(
    kind: str,
    *,
    confidence: str,
    dataset: str = "applicant_profiles",
    outcome: str = steward_assist.OUTCOME_CONFIRM,
) -> steward_assist.Recommendation:
    """Return a recommendation of one kind of task."""
    return steward_assist.Recommendation(
        task_kind=kind,
        task_id=f"{kind}_1",
        record_version=1,
        outcome=outcome,
        confidence=confidence,
        evidence={"source_dataset": dataset},
        reason="the evidence agrees.",
    )


def test_a_sure_link_of_an_undo_supported_family_may_be_accepted_in_a_batch(
    seeded: Settings,
) -> None:
    """The batch takes what the assistant is sure of and the steward can undo."""
    proposal_id = propose(seeded, record_id="ERP-BL-00412")
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            proposal = steward_assist.recommend(
                session, steward_assist.Task("link", proposal_id), settings=seeded
            )
    finally:
        factory.dispose()

    assert proposal.confidence == steward_assist.CONFIDENCE_HIGH
    assert proposal.evidence["source_dataset"] == "business_licensing_register"
    assert steward_assist.batch_family(proposal.evidence) == "owner_party"
    assert steward_assist.batch_refusal(proposal) == ""
    assert steward_assist.is_batch_eligible(proposal) is True


def test_a_recommendation_that_is_not_sure_is_never_accepted_in_a_batch() -> None:
    """Only a High recommendation may be accepted without reading it again."""
    proposal = recommendation("link", confidence=steward_assist.CONFIDENCE_REVIEW)

    assert steward_assist.batch_refusal(proposal) == "its confidence is no longer High"
    assert steward_assist.is_batch_eligible(proposal) is False


def test_a_held_recommendation_is_never_accepted_in_a_batch() -> None:
    """A recommendation held for a person is read, never accepted."""
    proposal = recommendation("link", confidence=steward_assist.CONFIDENCE_HELD)

    assert steward_assist.is_batch_eligible(proposal) is False


def test_a_data_issue_is_never_accepted_in_a_batch() -> None:
    """A data issue has no service action, so a batch never offers it."""
    proposal = recommendation(
        "issue", confidence=steward_assist.CONFIDENCE_HIGH, outcome=steward_assist.OUTCOME_RESOLVE
    )

    assert "issue" in steward_assist.batch_refusal(proposal)
    assert steward_assist.is_batch_eligible(proposal) is False


def test_a_parcel_link_is_never_accepted_in_a_batch() -> None:
    """A parcel link is not reversed by an action of the City."""
    proposal = recommendation(
        "parcel",
        confidence=steward_assist.CONFIDENCE_HIGH,
        dataset="parcel_register",
        outcome=steward_assist.OUTCOME_APPROVE_PARCEL,
    )

    assert "parcel" in steward_assist.batch_refusal(proposal)
    assert steward_assist.is_batch_eligible(proposal) is False


def test_a_correction_is_never_accepted_in_a_batch() -> None:
    """A correction moves a case on, so it is not accepted in a batch."""
    proposal = recommendation(
        "case", confidence=steward_assist.CONFIDENCE_HIGH, outcome=steward_assist.OUTCOME_ACCEPT
    )

    assert "case" in steward_assist.batch_refusal(proposal)
    assert steward_assist.is_batch_eligible(proposal) is False


def test_a_record_of_a_family_without_a_reversal_is_never_accepted_in_a_batch() -> None:
    """A family the City cannot reverse is only ever suggested to a person."""
    proposal = recommendation(
        "link", confidence=steward_assist.CONFIDENCE_HIGH, dataset="parcel_register"
    )

    assert steward_assist.batch_family(proposal.evidence) == "parcel"
    assert "reversal" in steward_assist.batch_refusal(proposal)
    assert steward_assist.is_batch_eligible(proposal) is False


def test_a_record_of_an_unknown_dataset_is_never_accepted_in_a_batch() -> None:
    """A dataset the City does not map has no family and no reversal."""
    proposal = recommendation(
        "link", confidence=steward_assist.CONFIDENCE_HIGH, dataset="a_dataset_the_city_does_not_know"
    )

    assert steward_assist.batch_family(proposal.evidence) == ""
    assert "reversal" in steward_assist.batch_refusal(proposal)
    assert steward_assist.is_batch_eligible(proposal) is False
