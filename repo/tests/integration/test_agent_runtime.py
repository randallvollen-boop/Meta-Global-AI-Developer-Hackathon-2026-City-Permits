"""The durable work queue of the agents.

The runtime records one piece of work per row, with a status column and an
attempt count.  Two workers never commit the same work, and the controlled
demonstration data is never eligible for automatic work.

A manual run goes through the same queue: the work is queued, taken, run and
finished, so the queue records the attempt.  A manual run is bounded by the
stored policy and never calls the model provider.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import select, update

from acme_city.agents.control import AgentControlService
from acme_city.agents.eligibility import eligible_applications
from acme_city.agents.intake import waiting_applications
from acme_city.agents.policy import current_policy
from acme_city.agents.runtime import (
    AgentRuntime,
    batch_limit,
    retry_allowed,
    run_agent,
    run_batch,
    work_key,
    work_status_for,
)
from acme_city.agents.summary import operator_summary
from acme_city.core.clock import utc_now
from acme_city.core.config import Settings
from acme_city.core.errors import ValidationError
from acme_city.core.ids import new_id
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.muse.client import MuseClient
from acme_city.muse.image_client import MuseImageClient
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import agent_ops, model_run, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.portal_intake.scenarios import build_scenario
from acme_city.portal_intake.service import INTAKE_AGENT_ID, IntakeService
from acme_city.triage.service import service_actor

#: The repository root, so the test can read the acceptance-test data.
REPO = Path(__file__).resolve().parents[2]

#: The fence scenarios of the two protected fence rules.
FENCE_SCENARIOS = ("fence-conforming-rear", "fence-front-too-tall")


@pytest.fixture()
def environment(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'agent-runtime.db'}",
            "ACME_SECRET_KEY": "agent-runtime-test-secret-value",
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


@pytest.fixture()
def hosted_environment(tmp_path: Path):
    """Return settings of a hosted demonstration with a key and the provider on.

    The credential is an inert test only value: it never leaves this process
    and it is never a real key.
    """
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'hosted-agent-runtime.db'}",
            "ACME_SECRET_KEY": "hosted-agent-runtime-test-secret-value",
            "META_API_KEY": "hosted-test-only-not-a-real-credential",
            "ACME_MUSE_PROVIDER_ENABLED": "true",
            "ACME_PUBLIC_DEMO": "true",
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


def _arrival(
    session,
    settings: Settings,
    scenario: str = "deck-high",
    *,
    sequence_start: int = 1,
) -> permit.Application:
    """Return one genuine arrival, submitted through the outside intake."""
    record = build_scenario(scenario, sequence_start=sequence_start)[0]
    result = IntakeService(session, settings=settings).submit_record(
        record, service_actor(session, INTAKE_AGENT_ID)
    )
    assert result.application_id is not None
    application = session.get(permit.Application, result.application_id)
    assert application is not None
    return application


def _another_arrival(session, settings: Settings, sequence_start: int = 2) -> permit.Application:
    """Return one more arrival, with a portal reference of its own."""
    return _arrival(session, settings, sequence_start=sequence_start)


def _wake(session, agent_key: str = agent_models.AGENT_INTAKE) -> None:
    """Wake one agent, the way the operator does."""
    service = AgentControlService(session)
    service.ensure_defaults()
    row = service.state(agent_key)
    assert row is not None
    row.mode = agent_models.AGENT_AWAKE
    session.flush()


def _acceptance_application_ids() -> set[str]:
    """Return the application ids the acceptance tests work on."""
    found: set[str] = set()
    for path in sorted((REPO / "tests" / "acceptance").glob("test_*.py")):
        found.update(re.findall(r"app_[a-z0-9_]+", path.read_text(encoding="utf-8")))
    return found


def _controlled_case(session) -> permit.Application:
    """Return one seeded case of the controlled demonstration."""
    row = session.execute(
        select(permit.Application).where(permit.Application.scenario_id == "D01")
    ).scalars().first()
    assert row is not None
    return row


def test_the_queue_records_one_piece_of_work_with_a_status_and_an_attempt_count(
    environment: Settings,
) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = _arrival(session, environment)
            runtime = AgentRuntime(session)
            row = runtime.enqueue(application)
            assert (row.status, row.attempts) == (agent_ops.WORK_PENDING, 0)
            assert row.work_key == work_key(application, agent_models.AGENT_INTAKE)
            # The same work is never queued twice.
            again = runtime.enqueue(application)
            assert again.id == row.id
            rows = session.execute(
                select(agent_ops.AgentWorkQueue).where(
                    agent_ops.AgentWorkQueue.application_id == application.id
                )
            ).scalars().all()
            assert len(rows) == 1
            # The queue reports the waiting work.
            assert [row.id for row in runtime.pending()] == [row.id]
    finally:
        factory.dispose()


def test_two_workers_never_commit_the_same_work(environment: Settings) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = _arrival(session, environment)
            runtime = AgentRuntime(session)
            row = runtime.enqueue(application)
            # The first worker takes the work and counts the attempt.
            claimed = runtime.claim(row.id)
            assert claimed is not None
            assert (claimed.status, claimed.attempts) == (agent_ops.WORK_RUNNING, 1)
            # The second worker cannot take the same work.
            assert runtime.claim(row.id) is None
            # Only the worker that holds the work may finish it.
            finished = runtime.finish(row.id, 1, agent_ops.WORK_COMPLETED, note="done")
            assert finished is not None
            assert finished.status == agent_ops.WORK_COMPLETED
            assert runtime.finish(row.id, 1, agent_ops.WORK_COMPLETED) is None
            assert runtime.claim(row.id) is None
    finally:
        factory.dispose()


def test_a_late_finish_of_an_earlier_attempt_is_refused(environment: Settings) -> None:
    """A finish names its attempt, so a late one changes nothing."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = _arrival(session, environment)
            runtime = AgentRuntime(session)
            row = runtime.enqueue(application)
            first = runtime.claim(row.id)
            assert first is not None
            assert first.attempts == 1
            assert runtime.finish(row.id, 1, agent_ops.WORK_FAILED, note="it failed") is not None
            # The work waits for another attempt and is taken again.
            assert runtime.reopen(row.id) is not None
            second = runtime.claim(row.id)
            assert second is not None
            assert second.attempts == 2
            # The late finish of the first attempt is refused: the second
            # attempt holds the work.
            assert runtime.finish(row.id, 1, agent_ops.WORK_COMPLETED, note="too late") is None
            session.refresh(row)
            assert row.status == agent_ops.WORK_RUNNING
            assert row.attempts == 2
            # The finish of the attempt that holds the work is recorded.
            finished = runtime.finish(row.id, 2, agent_ops.WORK_COMPLETED, note="done")
            assert finished is not None
            assert finished.status == agent_ops.WORK_COMPLETED
    finally:
        factory.dispose()


def test_the_clock_is_read_at_the_claim_and_at_the_finish(environment: Settings) -> None:
    """The row carries the moment of the attempt, not the moment of the queue."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = _arrival(session, environment)
            runtime = AgentRuntime(session)
            row = runtime.enqueue(application)
            before = utc_now()
            claimed = runtime.claim(row.id)
            assert claimed is not None
            assert claimed.claimed_at is not None
            assert before <= claimed.claimed_at <= utc_now()
            finished = runtime.finish(row.id, 1, agent_ops.WORK_COMPLETED, note="done")
            assert finished is not None
            assert finished.finished_at is not None
            assert claimed.claimed_at <= finished.finished_at <= utc_now()
            # A test may pass its own moment instead of the clock.
            moment = utc_now()
            other = AgentRuntime(session, now=moment)
            second = other.enqueue(
                _arrival(session, environment, scenario="shed-large")
            )
            claimed = other.claim(second.id)
            assert claimed is not None
            assert claimed.claimed_at == moment
    finally:
        factory.dispose()


def test_a_second_attempt_is_counted(environment: Settings) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = _arrival(session, environment)
            runtime = AgentRuntime(session)
            row = runtime.enqueue(application)
            runtime.claim(row.id)
            runtime.finish(row.id, 1, agent_ops.WORK_FAILED, note="the run failed")
            # A failed piece of work waits for another attempt.  The retry
            # itself is the failure-recovery slice; here the waiting work is
            # put back by hand to show that the attempt count grows.
            session.execute(
                update(agent_ops.AgentWorkQueue)
                .where(agent_ops.AgentWorkQueue.id == row.id)
                .values(status=agent_ops.WORK_PENDING)
            )
            session.expire_all()
            assert runtime.counts()["retrying"] == 1
            again = runtime.claim(row.id)
            assert again is not None
            assert (again.status, again.attempts) == (agent_ops.WORK_RUNNING, 2)
    finally:
        factory.dispose()


def test_the_protected_fixtures_are_never_eligible(environment: Settings) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            eligible = {row.id for row in eligible_applications(session)}
            # The D01-D11 cases of the demonstration carry a scenario id, so
            # they are the fixed fixture and not an arrival.
            seeded = session.execute(
                select(permit.Application).where(permit.Application.scenario_id.is_not(None))
            ).scalars().all()
            assert len(seeded) >= 11
            assert not eligible & {row.id for row in seeded}
            # The cases the acceptance tests work on are those same controlled
            # cases, and they are never eligible either.
            acceptance_ids = _acceptance_application_ids()
            assert acceptance_ids
            assert not eligible & acceptance_ids
            # The fixed fence scenarios are data, not cases: the rule evaluator
            # reads them.  No case of the controlled demonstration is eligible
            # at all, so none of the protected data can start on its own.
            for name in FENCE_SCENARIOS:
                (record,) = build_scenario(name)
                assert not session.execute(
                    select(permit.Application).where(
                        permit.Application.source_application_number == record.portal_reference
                    )
                ).scalars().all()
            assert not eligible & {
                row.id for row in session.execute(select(permit.Application)).scalars().all()
            }
    finally:
        factory.dispose()


def test_the_queue_is_empty_after_a_reset(environment: Settings) -> None:
    """A reset clears the queue: no work of the old demonstration survives."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            runtime = AgentRuntime(session)
            runtime.enqueue(_arrival(session, environment))
            assert runtime.counts()["pending"] == 1
        bundle = FixtureBundle.load()
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
        with factory() as session:
            runtime = AgentRuntime(session)
            assert runtime.counts()["pending"] == 0
            assert runtime.counts()["running"] == 0
            rows = session.execute(select(agent_ops.AgentWorkQueue)).scalars().all()
            assert rows == []
    finally:
        factory.dispose()


def test_a_fresh_arrival_is_eligible_and_a_worked_case_is_not(
    environment: Settings,
) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = _arrival(session, environment)
            eligible = {row.id for row in eligible_applications(session)}
            assert application.id in eligible
            # A case that is queued is not eligible a second time.
            AgentRuntime(session).enqueue(application)
            session.flush()
            eligible = {row.id for row in eligible_applications(session)}
            assert application.id not in eligible
            # A case that was worked before is history and never eligible.
            other = _arrival(session, environment, scenario="shed-large")
            session.add(
                agent_models.AgentRun(
                    id=new_id("agentrun"),
                    correlation_id=new_id("corr"),
                    agent_key=agent_models.AGENT_INTAKE,
                    application_id=other.id,
                    service_identity_id=INTAKE_AGENT_ID,
                    triggered_by=None,
                    started_at=utc_now(),
                    finished_at=utc_now(),
                    outcome="completed",
                )
            )
            session.flush()
            eligible = {row.id for row in eligible_applications(session)}
            assert other.id not in eligible
    finally:
        factory.dispose()


def test_the_waiting_cases_and_the_eligible_cases_share_one_clause(
    environment: Settings,
) -> None:
    """One clause decides both, and only the history of a case narrows it."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = _arrival(session, environment)
            waiting = {row.id for row in waiting_applications(session)}
            eligible = {row.id for row in eligible_applications(session)}
            assert application.id in waiting
            assert application.id in eligible
            # A case that is in the queue still waits for a person, but the
            # automatic work never takes it a second time.
            AgentRuntime(session).enqueue(application)
            session.flush()
            waiting = {row.id for row in waiting_applications(session)}
            eligible = {row.id for row in eligible_applications(session)}
            assert application.id in waiting
            assert application.id not in eligible
            # Every case the agents may pick up on their own waits for the
            # intake agent.
            assert eligible <= waiting
    finally:
        factory.dispose()


def test_the_queue_counts_report_the_state_of_the_work(environment: Settings) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            runtime = AgentRuntime(session)
            assert runtime.counts()["pending"] == 0
            first = runtime.enqueue(_arrival(session, environment))
            second = runtime.enqueue(_arrival(session, environment, scenario="shed-large"))
            assert runtime.counts()["pending"] == 2
            # The operator home reads the same queue.
            assert operator_summary(session)["queued"] == 2
            runtime.claim(first.id)
            assert runtime.counts()["running"] == 1
            runtime.claim(second.id)
            runtime.finish(second.id, 1, agent_ops.WORK_HELD, note="a person is asked")
            assert runtime.counts()["held"] == 1
            assert operator_summary(session)["queued"] == 0
            assert operator_summary(session)["retrying"] == 0
    finally:
        factory.dispose()


def test_a_manual_run_goes_through_the_work_queue(environment: Settings) -> None:
    """A manual run is an attempt of the queue, and the run names it."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            _wake(session)
            application = _arrival(session, environment)
            result = run_agent(
                session,
                application=application,
                agent_key=agent_models.AGENT_INTAKE,
                triggered_by="persona_agent_operator",
                settings=environment,
            )
            assert result.status == work_status_for(result.outcome)
            work = session.get(agent_ops.AgentWorkQueue, result.work_id)
            assert work is not None
            assert work.status == result.status
            assert work.attempts == 1
            assert work.agent_key == agent_models.AGENT_INTAKE
            assert work.application_id == application.id
            # The run and the queue name each other.
            run = session.get(agent_models.AgentRun, result.run_id)
            assert run is not None
            assert dict(run.inputs or {})["work_id"] == result.work_id
    finally:
        factory.dispose()


def test_a_second_manual_run_of_the_same_case_counts_another_attempt(
    environment: Settings,
) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            _wake(session)
            application = _arrival(session, environment)
            first = run_agent(
                session,
                application=application,
                agent_key=agent_models.AGENT_INTAKE,
                triggered_by="persona_agent_operator",
                settings=environment,
            )
            second = run_agent(
                session,
                application=application,
                agent_key=agent_models.AGENT_INTAKE,
                triggered_by="persona_agent_operator",
                settings=environment,
            )
            assert first.work_id == second.work_id
            assert second.attempts == 2
            rows = session.execute(select(agent_ops.AgentWorkQueue)).scalars().all()
            assert len(rows) == 1
    finally:
        factory.dispose()


def test_a_manual_batch_is_bounded_by_the_stored_policy(environment: Settings) -> None:
    """The batch names the cases the policy allows, and no more."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            _wake(session)
            policy = current_policy(session)
            assert policy is not None
            policy.max_batch_size = 2
            session.flush()
            cases = [
                _arrival(session, environment),
                _another_arrival(session, environment, sequence_start=2),
            ]
            third = _another_arrival(session, environment, sequence_start=3)
            results = run_batch(
                session,
                cases=[*cases, third],
                agent_key=agent_models.AGENT_INTAKE,
                triggered_by="persona_agent_operator",
                settings=environment,
            )
            assert len(results) == 2
            assert [result.application_id for result in results] == [
                cases[0].id,
                cases[1].id,
            ]
            # The case that was not in the batch still waits for the agent.
            session.refresh(third)
            assert third.status == "submitted"
            assert len(session.execute(select(agent_ops.AgentWorkQueue)).scalars().all()) == 2
    finally:
        factory.dispose()


def test_an_hour_that_is_used_up_refuses_the_run(environment: Settings) -> None:
    """The hourly limit of the City is a limit of the hour."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            _wake(session)
            policy = current_policy(session)
            assert policy is not None
            policy.runs_per_hour = 1
            session.flush()
            first = run_agent(
                session,
                application=_arrival(session, environment),
                agent_key=agent_models.AGENT_INTAKE,
                triggered_by="persona_agent_operator",
                settings=environment,
            )
            assert first.attempts == 1
            with pytest.raises(ValidationError) as raised:
                run_agent(
                    session,
                    application=_another_arrival(session, environment),
                    agent_key=agent_models.AGENT_INTAKE,
                    triggered_by="persona_agent_operator",
                    settings=environment,
                )
            assert "hourly limit" in str(raised.value)
            # The refused run left no work behind.
            rows = session.execute(select(agent_ops.AgentWorkQueue)).scalars().all()
            assert len(rows) == 1
    finally:
        factory.dispose()


def test_the_batch_limit_is_read_from_the_stored_policy(environment: Settings) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            policy = current_policy(session)
            assert policy is not None
            # The stored values are not the defaults, so a limit that ignores
            # the policy cannot pass this test.
            policy.max_batch_size = 7
            policy.runs_per_hour = 11
            session.flush()
            limit = batch_limit(session)
            assert limit.max_batch_size == 7
            assert limit.runs_per_hour == 11
            assert limit.runs_this_hour == 0
            assert limit.remaining_runs == 11
    finally:
        factory.dispose()


def test_a_controlled_case_is_never_worked(environment: Settings) -> None:
    """A case of the fixed demonstration is never an arrival and is never worked."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            _wake(session)
            application = _controlled_case(session)
            status = application.status
            version = application.version
            with pytest.raises(ValidationError) as raised:
                run_agent(
                    session,
                    application=application,
                    agent_key=agent_models.AGENT_INTAKE,
                    triggered_by="persona_agent_operator",
                    settings=environment,
                )
            assert "controlled demonstration case" in str(raised.value)
            # The case is exactly as it was, and no work was queued for it.
            session.refresh(application)
            assert application.status == status
            assert application.version == version
            rows = session.execute(select(agent_ops.AgentWorkQueue)).scalars().all()
            assert rows == []
            runs = session.execute(select(agent_models.AgentRun)).scalars().all()
            assert runs == []
    finally:
        factory.dispose()


def test_a_sleeping_agent_is_refused_before_the_work_is_queued(
    environment: Settings,
) -> None:
    """A sleeping agent waits for its cases instead of failing a piece of work."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = _arrival(session, environment)
            with pytest.raises(ValidationError) as raised:
                run_agent(
                    session,
                    application=application,
                    agent_key=agent_models.AGENT_INTAKE,
                    triggered_by="persona_agent_operator",
                    settings=environment,
                )
            assert "asleep" in str(raised.value)
            # No work was queued and no attempt was counted.
            rows = session.execute(select(agent_ops.AgentWorkQueue)).scalars().all()
            assert rows == []
            runs = session.execute(select(agent_models.AgentRun)).scalars().all()
            assert runs == []
    finally:
        factory.dispose()


def test_a_manual_run_never_calls_the_model_provider(
    hosted_environment: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hosted demonstration with a key still runs on the built in logic."""

    calls: list[str] = []

    def record_client_call(*args: object, **kwargs: object) -> None:
        calls.append("the model provider")
        raise AssertionError("a manual run must not call the model provider")

    def record_image_call(*args: object, **kwargs: object) -> None:
        calls.append("the image provider")
        raise AssertionError("a manual run must not call the model provider")

    monkeypatch.setattr(MuseClient, "create_response", record_client_call)
    monkeypatch.setattr(MuseImageClient, "generate", record_image_call)
    factory = SessionFactory(hosted_environment.database_url)
    try:
        with factory() as session:
            _wake(session)
            application = _arrival(session, hosted_environment)
            result = run_agent(
                session,
                application=application,
                agent_key=agent_models.AGENT_INTAKE,
                triggered_by="persona_agent_operator",
                settings=hosted_environment,
            )
            assert result.run_id
            work = session.get(agent_ops.AgentWorkQueue, result.work_id)
            assert work is not None
            assert work.status == result.status
            # The provider was never reached.  The calls are recorded, so a
            # run that reached the provider fails this test.
            assert calls == []
    finally:
        factory.dispose()


def test_a_run_without_a_key_records_the_built_in_provenance(environment: Settings) -> None:
    """The deterministic logic of the City records its own provenance.

    The run is not a replay of an earlier run and it is not a provider call:
    it says so, and the two records of the attempt name each other.
    """
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            _wake(session)
            application = _arrival(session, environment, scenario="fence-conforming-rear")
            result = run_agent(
                session,
                application=application,
                agent_key=agent_models.AGENT_INTAKE,
                triggered_by="persona_agent_operator",
                settings=environment,
            )
            rows = session.execute(select(model_run.ModelRun)).scalars().all()
            assert [row.mode for row in rows] == ["builtin"]
            recorded = rows[0]
            assert recorded.provider == "builtin"
            assert recorded.replay_of_run_id is None
            # The run of the agent names the run of the model and its engine.
            run = session.get(agent_models.AgentRun, result.run_id)
            assert run is not None
            inputs = dict(run.inputs or {})
            assert inputs["model_run_id"] == recorded.id
            assert inputs["engine"] == "builtin"
            # The run of the model names the run of the agent.
            assert recorded.input_refs["agent_run_id"] == run.id
    finally:
        factory.dispose()


def test_a_hosted_run_with_a_key_records_the_built_in_provenance(
    hosted_environment: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hosted demonstration never reaches the provider, not even with a key."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a manual run must not call the model provider")

    monkeypatch.setattr(MuseClient, "create_response", refuse)
    monkeypatch.setattr(MuseImageClient, "generate", refuse)
    factory = SessionFactory(hosted_environment.database_url)
    try:
        with factory() as session:
            _wake(session)
            application = _arrival(
                session, hosted_environment, scenario="fence-conforming-rear"
            )
            run_agent(
                session,
                application=application,
                agent_key=agent_models.AGENT_INTAKE,
                triggered_by="persona_agent_operator",
                settings=hosted_environment,
            )
            rows = session.execute(select(model_run.ModelRun)).scalars().all()
            assert [row.mode for row in rows] == ["builtin"]
            assert rows[0].provider == "builtin"
    finally:
        factory.dispose()


def test_the_replay_path_keeps_its_label_and_its_identifier(environment: Settings) -> None:
    """The replay of an earlier run keeps the provenance it always had."""
    from acme_city.agents.extraction import replay_extraction
    from acme_city.triage.service import service_actor

    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = _arrival(session, environment, scenario="fence-conforming-rear")
            actor = service_actor(session, INTAKE_AGENT_ID)
            result = replay_extraction(session, application, actor)
            assert result["mode"] == "replay"
            rows = session.execute(select(model_run.ModelRun)).scalars().all()
            assert [row.mode for row in rows] == ["replay"]
            assert rows[0].provider == "meta"
            assert rows[0].model == "muse-spark-1.3"
            assert rows[0].replay_of_run_id == "intake-document-replay"
    finally:
        factory.dispose()


def _work_of(session, application_id: str) -> agent_ops.AgentWorkQueue:
    """Return the queued work of one case."""
    row = session.execute(
        select(agent_ops.AgentWorkQueue).where(
            agent_ops.AgentWorkQueue.application_id == application_id
        )
    ).scalars().first()
    assert row is not None, "the case has no recorded work"
    return row


def test_a_failed_run_is_recorded_and_the_work_can_be_tried_again(
    environment: Settings,
) -> None:
    """A technical failure is kept, and the retry works the case again."""
    from acme_city.agents.runtime import AgentRunFailed, retry_agent
    from acme_city.permits.guard import ARCHIVED_STATUS

    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = _arrival(session, environment)
            application_id = application.id
            _wake(session)
            # The case is archived, so the agent refuses to work on it and the
            # attempt stops.
            row = session.get(permit.Application, application_id)
            row.status = ARCHIVED_STATUS
            session.flush()
            with pytest.raises(AgentRunFailed):
                run_agent(
                    session,
                    application=row,
                    agent_key=agent_models.AGENT_INTAKE,
                    triggered_by="persona_agent_operator",
                    settings=environment,
                )
        with factory() as session:
            work = _work_of(session, application_id)
            assert work.status == agent_ops.WORK_FAILED
            assert work.attempts == 1
            assert "archived" in (work.note or "")
            # No run is left open by the attempt that stopped.
            runs = session.execute(
                select(agent_models.AgentRun).where(
                    agent_models.AgentRun.application_id == application_id
                )
            ).scalars().all()
            assert all(row.finished_at is not None for row in runs)
        # The case is restored, so the retry can work on it.
        with transaction(factory) as session:
            row = session.get(permit.Application, application_id)
            row.status = "submitted"
            session.flush()
            result = retry_agent(
                session,
                application=row,
                agent_key=agent_models.AGENT_INTAKE,
                triggered_by="persona_agent_operator",
                settings=environment,
            )
            assert result.outcome != "failed"
        with factory() as session:
            work = _work_of(session, application_id)
            assert work.status == agent_ops.WORK_COMPLETED
            assert work.attempts == 2
    finally:
        factory.dispose()


def test_a_stopped_run_leaves_no_partial_rows(
    environment: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that stops after a node wrote saves no business change."""
    from acme_city.agents.intake import IntakeAgent
    from acme_city.agents.runtime import AgentRunFailed

    def _stopped(self, *args, **kwargs):
        raise RuntimeError("the locator stopped")

    # The locator fails after the extractor wrote its observation.
    monkeypatch.setattr(IntakeAgent, "_node_address_locator", _stopped)

    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = _arrival(session, environment)
            application_id = application.id
            _wake(session)
            before_observations = len(
                session.execute(select(permit.ExtractionObservation)).scalars().all()
            )
            before_model_runs = len(
                session.execute(select(model_run.ModelRun)).scalars().all()
            )
            row = session.get(permit.Application, application_id)
            assert row is not None
            with pytest.raises(AgentRunFailed):
                run_agent(
                    session,
                    application=row,
                    agent_key=agent_models.AGENT_INTAKE,
                    triggered_by="persona_agent_operator",
                    settings=environment,
                )
        with factory() as session:
            # The failure is recorded on the work, so a person sees it.
            work = _work_of(session, application_id)
            assert work.status == agent_ops.WORK_FAILED
            assert "the locator stopped" in (work.note or "")
            # The observation and the model run of the stopped attempt are
            # gone: the attempt saved nothing.
            assert (
                len(session.execute(select(permit.ExtractionObservation)).scalars().all())
                == before_observations
            )
            assert (
                len(session.execute(select(model_run.ModelRun)).scalars().all())
                == before_model_runs
            )
            document_ids = session.execute(
                select(permit.Document.id).where(
                    permit.Document.application_id == application_id
                )
            ).scalars().all()
            observations = session.execute(
                select(permit.ExtractionObservation).where(
                    permit.ExtractionObservation.document_id.in_(document_ids)
                )
            ).scalars().all()
            assert observations == []
            runs = session.execute(
                select(agent_models.AgentRun).where(
                    agent_models.AgentRun.application_id == application_id
                )
            ).scalars().all()
            assert len(runs) == 1, "the attempt is not recorded"
            assert runs[0].outcome == "failed"
            assert runs[0].finished_at is not None
    finally:
        factory.dispose()


def test_a_person_may_try_the_failed_work_again(environment: Settings) -> None:
    """How often a person tries the failed work is the operator's decision."""
    from acme_city.agents.runtime import AgentRunFailed, retry_agent
    from acme_city.permits.guard import ARCHIVED_STATUS

    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = _arrival(session, environment)
            application_id = application.id
            _wake(session)
            # The case stays archived, so every attempt stops the same way.
            row = session.get(permit.Application, application_id)
            row.status = ARCHIVED_STATUS
            session.flush()
        with transaction(factory) as session:
            row = session.get(permit.Application, application_id)
            with pytest.raises(AgentRunFailed):
                run_agent(
                    session,
                    application=row,
                    agent_key=agent_models.AGENT_INTAKE,
                    triggered_by="persona_agent_operator",
                    settings=environment,
                )
        for _attempt in range(2):
            with transaction(factory) as session:
                row = session.get(permit.Application, application_id)
                with pytest.raises(AgentRunFailed):
                    # The second and the third attempt fail the same way.
                    retry_agent(
                        session,
                        application=row,
                        agent_key=agent_models.AGENT_INTAKE,
                        triggered_by="persona_agent_operator",
                        settings=environment,
                    )
        with factory() as session:
            work = _work_of(session, application_id)
            assert work.status == agent_ops.WORK_FAILED
            assert work.attempts == 3
        # A person may try the work a fourth time.
        with transaction(factory) as session:
            row = session.get(permit.Application, application_id)
            with pytest.raises(AgentRunFailed):
                retry_agent(
                    session,
                    application=row,
                    agent_key=agent_models.AGENT_INTAKE,
                    triggered_by="persona_agent_operator",
                    settings=environment,
                )
        with factory() as session:
            work = _work_of(session, application_id)
            assert work.status == agent_ops.WORK_FAILED
            assert work.attempts == 4
            assert retry_allowed(work), "the work may be tried again"
    finally:
        factory.dispose()


def test_a_work_that_waits_for_a_person_is_never_retried(environment: Settings) -> None:
    """A held work is not a technical failure."""
    from acme_city.agents.runtime import retry_agent

    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = _arrival(session, environment)
            application_id = application.id
            _wake(session)
            run_agent(
                session,
                application=application,
                agent_key=agent_models.AGENT_INTAKE,
                triggered_by="persona_agent_operator",
                settings=environment,
            )
        with factory() as session:
            work = _work_of(session, application_id)
            assert work.status in (agent_ops.WORK_COMPLETED, agent_ops.WORK_HELD)
            if work.status == agent_ops.WORK_COMPLETED:
                return
        with transaction(factory) as session:
            row = session.get(permit.Application, application_id)
            with pytest.raises(ValidationError) as raised:
                retry_agent(
                    session,
                    application=row,
                    agent_key=agent_models.AGENT_INTAKE,
                    triggered_by="persona_agent_operator",
                    settings=environment,
                )
            assert "did not fail" in str(raised.value)
    finally:
        factory.dispose()
