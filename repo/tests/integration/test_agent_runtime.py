"""The durable work queue of the agents.

The runtime records one piece of work per row, with a status column and an
attempt count.  Two workers never commit the same work, and the controlled
demonstration data is never eligible for automatic work.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import select, update

from acme_city.agents.eligibility import eligible_applications
from acme_city.agents.runtime import AgentRuntime, work_key
from acme_city.agents.summary import operator_summary
from acme_city.core.clock import utc_now
from acme_city.core.config import Settings
from acme_city.core.ids import new_id
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.kernel.inputs import build_inputs
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import agent_ops, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.portal_intake.scenarios import build_scenario
from acme_city.portal_intake.service import INTAKE_AGENT_ID, IntakeService
from acme_city.rules.evaluator import evaluate, overall_status
from acme_city.rules.service import RuleCatalogService
from acme_city.triage.service import service_actor

#: The repository root, so the test can read the acceptance-test data.
REPO = Path(__file__).resolve().parents[2]

#: The fence scenarios of the two protected fence rules.
FENCE_SCENARIOS = ("fence-conforming-rear", "fence-front-too-tall")

#: The protected fence rules and the scenario each of them is measured with.
FENCE_RULES = {"DF-1": "fence-front-too-tall", "DF-2": "fence-conforming-rear"}


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


def _arrival(session, settings: Settings, scenario: str = "deck-high") -> permit.Application:
    """Return one genuine arrival, submitted through the outside intake."""
    record = build_scenario(scenario)[0]
    result = IntakeService(session, settings=settings).submit_record(
        record, service_actor(session, INTAKE_AGENT_ID)
    )
    assert result.application_id is not None
    application = session.get(permit.Application, result.application_id)
    assert application is not None
    return application


def _acceptance_application_ids() -> set[str]:
    """Return the application ids the acceptance tests work on."""
    found: set[str] = set()
    for path in sorted((REPO / "tests" / "acceptance").glob("test_*.py")):
        found.update(re.findall(r"app_[a-z0-9_]+", path.read_text(encoding="utf-8")))
    return found


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
            finished = runtime.finish(row.id, agent_ops.WORK_COMPLETED, note="done")
            assert finished is not None
            assert finished.status == agent_ops.WORK_COMPLETED
            assert runtime.finish(row.id, agent_ops.WORK_COMPLETED) is None
            assert runtime.claim(row.id) is None
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
            runtime.finish(row.id, agent_ops.WORK_FAILED, note="the run failed")
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


def test_a_runtime_cycle_leaves_the_protected_fence_outcomes_unchanged(
    environment: Settings,
) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            runtime = AgentRuntime(session)
            for application in eligible_applications(session):
                runtime.enqueue(application)
            catalog = RuleCatalogService(session)
            for rule_id, scenario in FENCE_RULES.items():
                (record,) = build_scenario(scenario)
                rule_set = catalog.resolve("executable", record.permit_type_key, record.received_at)
                results = evaluate(build_inputs(record.submitted_facts), rule_set)
                assert overall_status(results) == ("fail" if rule_id == "DF-1" else "pass")
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
            runtime.finish(second.id, agent_ops.WORK_HELD, note="a person is asked")
            assert runtime.counts()["held"] == 1
            assert operator_summary(session)["queued"] == 0
            assert operator_summary(session)["retrying"] == 0
    finally:
        factory.dispose()
