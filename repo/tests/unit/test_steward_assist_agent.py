"""The steward assistant as an agent: the grants, the bounds and the refusals.

The assistant prepares the work of the queue; the steward decides.  The
tests prove that the assistant runs only when the Data Steward asks it to and
only while it is awake, that one press is bounded, that every press leaves a
run trace, and that a recommendation that is held or stale is never accepted.
"""
# REQUIRES: PER-01, PER-04, SEC-01

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.agents import steward_assist as assistant
from acme_city.agents.control import AgentControlService, agent_mode
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from acme_city.core.ids import new_id
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_automation_demo import seed_automation
from acme_city.ingestion.schemas import IngestCommand, SourceRecordCommand
from acme_city.ingestion.service import IngestionService
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import registry, registry_automation, source
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.registry import steward_assist as recommenders
from acme_city.registry.schemas import MatchDecisionCommand, MatchProposalCommand
from acme_city.registry.service import RegistryService

#: The Data Steward: the only persona that works the queue.
STEWARD = ActorContext(actor_id="persona_data_steward", role_ids=frozenset())

#: The Agent Operator: the persona that wakes and sleeps the agents.
OPERATOR = ActorContext(actor_id="persona_agent_operator", role_ids=frozenset())

#: The Permit Reviewer: a persona that holds no grant of the queue.
REVIEWER = ActorContext(actor_id="persona_permit_reviewer", role_ids=frozenset())

#: The licence the demonstration proposes against a master record.
LICENCE = "ERP-BL-00412"


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'steward-assist-agent.db'}",
            "ACME_SECRET_KEY": "steward-assist-agent-test-secret",
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


def propose(settings: Settings, *, record_id: str = LICENCE) -> str:
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


def wake(settings: Settings, agent_key: str = assistant.AGENT_KEY) -> None:
    """Wake one agent, the way the Agent Operator does."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            AgentControlService(session).set_mode(agent_key, "awake", OPERATOR)
    finally:
        factory.dispose()


def prepare(settings: Settings, tasks, actor: ActorContext = STEWARD) -> assistant.Prepared:
    """Ask the assistant to prepare the recommendations of the given tasks."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            result = assistant.prepare(session, tasks=tasks, actor=actor)
            session.commit()
            return result
    finally:
        factory.dispose()


def many_proposals(settings: Settings, count: int) -> list[str]:
    """Record many proposals of the same source record, for the bound."""
    factory = SessionFactory(settings.database_url)
    identifiers: list[str] = []
    try:
        with transaction(factory) as session:
            snapshot = session.execute(
                select(source.SourceSnapshot).where(
                    source.SourceSnapshot.source_record_id == LICENCE
                )
            ).scalars().first()
            assert snapshot is not None
            for index in range(count):
                identifier = new_id("proposal")
                session.add(
                    registry.MatchProposal(
                        id=identifier,
                        source_snapshot_id=snapshot.source_snapshot_id,
                        correlation_id=new_id("corr"),
                        entity_id="party_cedarline",
                        candidate_ids=["party_cedarline"],
                        compared_fields=[],
                        supporting_evidence=[],
                        conflicting_evidence=[],
                        method="deterministic",
                        proposal_score=1.0,
                        score_is_calibrated=False,
                        disposition="unresolved",
                        created_by_actor_id=STEWARD.actor_id,
                    )
                )
                identifiers.append(identifier)
        return identifiers
    finally:
        factory.dispose()


def deliver_newer_licence(settings: Settings) -> None:
    """Deliver a newer version of the licence of the demonstration."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            IngestionService(session).ingest(
                IngestCommand(
                    source_system_id="erp_finance",
                    dataset_key="business_licensing_register",
                    records=[
                        SourceRecordCommand(
                            source_record_id=LICENCE,
                            source_record_version="3",
                            payload={
                                "license_number": "BL-2026-00412",
                                "holder_name": "Cedar Line Coffee Roasters",
                                "holder_ref": "party_cedarline",
                                "status": "active",
                                "valid_from": "2026-01-15",
                                "valid_to": "2026-12-31",
                                "business_address": "400 Lantern Row Unit 2",
                            },
                            source_updated_at=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
                        )
                    ],
                ),
                STEWARD,
            )
    finally:
        factory.dispose()


def decide_on_the_link(
    settings: Settings,
    *,
    decision: str = "reject",
    source_system_id: str = "erp_finance",
    dataset_key: str = "business_licensing_register",
    source_record_id: str = LICENCE,
) -> None:
    """Let the steward decide on the link of a source record."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            crosswalk = RegistryService(session).open_crosswalk(
                source_system_id, source_record_id
            )
            assert crosswalk is not None
            RegistryService(session).decide(
                MatchDecisionCommand(
                    decision=decision,
                    reason="the fictional steward decides on the link",
                    source_system_id=source_system_id,
                    dataset_key=dataset_key,
                    source_record_id=source_record_id,
                    crosswalk_id=crosswalk.id,
                    expected_version=crosswalk.version,
                ),
                STEWARD,
            )
    finally:
        factory.dispose()


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


# ------------------------------------------------------------------- the grants


def test_the_data_steward_holds_the_run_grant_of_the_assistant(seeded: Settings) -> None:
    """Only the Data Steward may ask the assistant for a recommendation."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            resolver = PermissionResolver(session)
            assert "agent.run.steward_assist" in {
                grant.permission_id for grant in resolver.grants_for(STEWARD.actor_id)
            }
            for other in ("persona_agent_operator", "persona_permit_reviewer"):
                assert "agent.run.steward_assist" not in {
                    grant.permission_id for grant in resolver.grants_for(other)
                }
    finally:
        factory.dispose()


def test_a_persona_without_the_grant_may_not_ask_the_assistant(seeded: Settings) -> None:
    """The Permit Reviewer is refused."""
    wake(seeded)
    proposal_id = propose(seeded)
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            with pytest.raises(PermissionDeniedError):
                assistant.prepare(
                    session,
                    tasks=[recommenders.Task("link", proposal_id)],
                    actor=REVIEWER,
                )
    finally:
        factory.dispose()


def test_the_agent_operator_may_not_ask_the_assistant(seeded: Settings) -> None:
    """The Agent Operator runs the agents of the City; the queue is not its work."""
    wake(seeded)
    proposal_id = propose(seeded)
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            with pytest.raises(PermissionDeniedError):
                assistant.prepare(
                    session,
                    tasks=[recommenders.Task("link", proposal_id)],
                    actor=OPERATOR,
                )
    finally:
        factory.dispose()


def test_only_the_operator_may_wake_the_assistant(seeded: Settings) -> None:
    """The wake and sleep switch belongs to the Agent Operator."""
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            with pytest.raises(PermissionDeniedError):
                AgentControlService(session).set_mode(
                    assistant.AGENT_KEY, "awake", STEWARD
                )
            control = AgentControlService(session)
            control.set_mode(assistant.AGENT_KEY, "awake", OPERATOR)
            assert control.state(assistant.AGENT_KEY).mode == "awake"
    finally:
        factory.dispose()


def test_a_sleeping_assistant_refuses_the_press(seeded: Settings) -> None:
    """Nothing runs while the assistant sleeps."""
    proposal_id = propose(seeded)
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            with pytest.raises(ValidationError) as refusal:
                assistant.prepare(
                    session,
                    tasks=[recommenders.Task("link", proposal_id)],
                    actor=STEWARD,
                )
            assert "asleep" in str(refusal.value)
    finally:
        factory.dispose()


# ------------------------------------------------------------------ the press


def test_a_press_prepares_the_recommendation_of_the_task(seeded: Settings) -> None:
    """The assistant records what it proposes and who asked for it."""
    wake(seeded)
    proposal_id = propose(seeded)
    result = prepare(seeded, [assistant.recommenders.Task("link", proposal_id)])

    assert len(result.recommendations) == 1
    row = result.recommendations[0]
    assert row.task_kind == "link"
    assert row.task_id == proposal_id
    assert row.confidence in {"high", "review", "held"}
    assert row.made_by_actor_id == assistant.SERVICE_ACTOR_ID
    assert row.reason


def test_every_press_leaves_a_run_trace(seeded: Settings) -> None:
    """A press is recorded in the run history of the operator."""
    wake(seeded)
    proposal_id = propose(seeded)
    result = prepare(seeded, [assistant.recommenders.Task("link", proposal_id)])

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            run = session.get(agent_models.AgentRun, result.run.id)
            assert run is not None
            assert run.agent_key == assistant.AGENT_KEY
            assert run.service_identity_id == assistant.SERVICE_ACTOR_ID
            assert run.triggered_by == STEWARD.actor_id
            assert run.outcome == "recommended"
            assert run.finished_at is not None
            assert run.inputs["engine"] == "builtin"
            assert run.inputs["task_ids"] == [proposal_id]
    finally:
        factory.dispose()


def test_one_press_prepares_at_most_twenty_tasks(seeded: Settings) -> None:
    """A press of the queue is bounded, so a long queue is worked in steps."""
    wake(seeded)
    identifiers = many_proposals(seeded, assistant.MAX_TASKS_PER_PRESS + 1)
    tasks = [recommenders.Task("link", identifier) for identifier in identifiers]
    result = prepare(seeded, tasks)

    assert len(result.recommendations) == assistant.MAX_TASKS_PER_PRESS
    assert result.run.inputs["requested"] == len(tasks)
    assert len(result.run.inputs["task_ids"]) == assistant.MAX_TASKS_PER_PRESS
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            stored = session.execute(
                select(StewardRecommendation).where(
                    StewardRecommendation.cleared.is_(False)
                )
            ).scalars().all()
            assert len(stored) == assistant.MAX_TASKS_PER_PRESS
            # The task that did not fit the press holds no recommendation.
            assert all(row.task_id != identifiers[-1] for row in stored)
    finally:
        factory.dispose()


def test_a_new_recommendation_replaces_the_earlier_one(seeded: Settings) -> None:
    """A task holds one recommendation at a time."""
    wake(seeded)
    proposal_id = propose(seeded)
    prepare(seeded, [assistant.recommenders.Task("link", proposal_id)])
    result = prepare(seeded, [assistant.recommenders.Task("link", proposal_id)])

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            stored = session.execute(
                select(StewardRecommendation).where(
                    StewardRecommendation.task_kind == "link",
                    StewardRecommendation.task_id == proposal_id,
                )
            ).scalars().all()
            assert len(stored) == 2
            assert sum(1 for row in stored if not row.cleared) == 1
            assert stored[0].cleared is True
            assert stored[1].cleared is False
    finally:
        factory.dispose()
    assert result.recommendations[0].cleared is False


def test_the_steward_can_clear_a_recommendation(seeded: Settings) -> None:
    """A recommendation the steward does not want is cleared, also while asleep."""
    wake(seeded)
    proposal_id = propose(seeded)
    prepare(seeded, [assistant.recommenders.Task("link", proposal_id)])
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            row = assistant.clear(
                session,
                task_kind="link",
                task_id=proposal_id,
                actor=STEWARD,
            )
            assert row.cleared is True
            assert row.cleared_at is not None
            assert assistant.recommendation_for(session, "link", proposal_id) is None
    finally:
        factory.dispose()


def test_clearing_a_task_without_a_recommendation_is_refused(seeded: Settings) -> None:
    """There is nothing to clear."""
    wake(seeded)
    proposal_id = propose(seeded)
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            with pytest.raises(NotFoundError):
                assistant.clear(
                    session, task_kind="link", task_id=proposal_id, actor=STEWARD
                )
    finally:
        factory.dispose()


# -------------------------------------------------------------- the refusals


def test_a_held_recommendation_is_refused(seeded: Settings) -> None:
    """A recommendation held for a person is never accepted."""
    wake(seeded)
    proposal_id = propose(seeded)
    prepare(seeded, [assistant.recommenders.Task("link", proposal_id)])
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            row = assistant.recommendation_for(session, "link", proposal_id)
            assert row is not None
            row.confidence = "held"
            session.flush()
            with pytest.raises(ValidationError) as refusal:
                assistant.refuse_unless_acceptable(session, row)
            assert "held" in str(refusal.value)
    finally:
        factory.dispose()


def test_a_stale_recommendation_is_refused(seeded: Settings) -> None:
    """A record that changed since the recommendation was made refuses it."""
    wake(seeded)
    proposal_id = propose(seeded)
    prepare(seeded, [assistant.recommenders.Task("link", proposal_id)])
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            row = assistant.recommendation_for(session, "link", proposal_id)
            assert row is not None
            party = session.get(registry.Party, "party_cedarline")
            assert party is not None
            party.version += 1
            session.flush()
            assert assistant.is_stale(session, row) is True
            with pytest.raises(ValidationError) as refusal:
                assistant.refuse_unless_acceptable(session, row)
            assert str(refusal.value) == assistant.STALE_MESSAGE
    finally:
        factory.dispose()


def test_a_link_that_was_proposed_again_is_stale(seeded: Settings) -> None:
    """A link that moved on since the recommendation refuses it."""
    wake(seeded)
    proposal_id = propose(seeded)
    prepare(seeded, [recommenders.Task("link", proposal_id)])
    # The steward proposes the same source record again: the link moves on.
    propose(seeded)
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            row = assistant.recommendation_for(session, "link", proposal_id)
            assert row is not None
            assert assistant.is_stale(session, row) is True
            with pytest.raises(ValidationError) as refusal:
                assistant.refuse_unless_acceptable(session, row)
            assert str(refusal.value) == assistant.STALE_MESSAGE
    finally:
        factory.dispose()


def test_a_link_a_person_decided_is_stale(seeded: Settings) -> None:
    """A link that was decided since the recommendation refuses it."""
    wake(seeded)
    proposal_id = propose(seeded)
    prepare(seeded, [recommenders.Task("link", proposal_id)])
    decide_on_the_link(seeded)
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            row = assistant.recommendation_for(session, "link", proposal_id)
            assert row is not None
            assert assistant.is_stale(session, row) is True
    finally:
        factory.dispose()


def test_a_source_record_that_changed_is_stale(seeded: Settings) -> None:
    """A source record with a newer version refuses the recommendation."""
    wake(seeded)
    proposal_id = propose(seeded)
    prepare(seeded, [recommenders.Task("link", proposal_id)])
    deliver_newer_licence(seeded)
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            row = assistant.recommendation_for(session, "link", proposal_id)
            assert row is not None
            assert assistant.is_stale(session, row) is True
    finally:
        factory.dispose()


def test_an_applied_link_a_person_changed_is_stale(seeded: Settings) -> None:
    """An applied link that was decided since the recommendation refuses it."""
    wake(seeded)
    application_id = applied_link(seeded)
    prepare(seeded, [recommenders.Task("automatic_link", application_id)])
    decide_on_the_link(
        seeded,
        decision="reject",
        source_system_id="permitting",
        dataset_key="applicant_profiles",
        source_record_id="PER-AP-0001",
    )
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            row = assistant.recommendation_for(session, "automatic_link", application_id)
            assert row is not None
            assert assistant.is_stale(session, row) is True
    finally:
        factory.dispose()


def test_an_applied_link_whose_versions_already_differ_is_not_stale(
    seeded: Settings,
) -> None:
    """The link of an application has its own version, and it is read as it is."""
    wake(seeded)
    application_id = applied_link(seeded)
    prepare(seeded, [recommenders.Task("automatic_link", application_id)])
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            row = assistant.recommendation_for(session, "automatic_link", application_id)
            assert row is not None
            application = session.get(
                registry_automation.RegistryAutomationApplication, application_id
            )
            assert application is not None
            crosswalk = session.get(registry.Crosswalk, application.crosswalk_id)
            assert crosswalk is not None
            # The application and the link carry versions of their own.
            assert int(row.evidence["crosswalk_version"]) == crosswalk.version
            assert application.version != crosswalk.version
            assert assistant.is_stale(session, row) is False
    finally:
        factory.dispose()


def test_the_steward_assistant_sleeps_after_a_reset(seeded: Settings) -> None:
    """The assistant is asleep until the Agent Operator wakes it."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            assert agent_mode(session, assistant.AGENT_KEY) == "asleep"
            assert AgentControlService(session).state(assistant.AGENT_KEY) is None
    finally:
        factory.dispose()
