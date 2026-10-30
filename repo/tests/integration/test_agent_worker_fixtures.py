"""The automatic processing worker of the agents.

The worker is the background half of the lane: it works the cases that
arrive with the built in logic of the City.  These tests hold it to the
four things it must never break: it stays off unless the deployment asks
for it, it never touches the controlled fixture of the demonstration, it
works the arrivals with the built in logic when there is no key, and it
never calls the model provider.
"""
# REQUIRES: PER-01, PER-04
# Automatic processing is bounded by the policy of the City, it never touches
# the fixed demonstration and it never calls the provider.

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.agents.control import AgentControlService
from acme_city.agents.intake import INTAKE_AGENT_ID, service_actor
from acme_city.agents.runtime import run_agent
from acme_city.agents.worker import WORKER_ACTOR_ID, AgentWorker
from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.configuration.service import ConfigurationService
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo, seeded_row_counts
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import agent_ops, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.models.model_run import ModelRun
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.portal_intake.scenarios import build_scenario

REPO = Path(__file__).resolve().parents[2]

# The controlled outcomes of the demonstration are observed by the regression
# module.  Its helpers are reused here, so the worker is measured against the
# same snapshot every other lane is measured against.
sys.path.insert(0, str(REPO / "tests" / "regression"))
from test_fixture_outcomes_snapshot import (  # noqa: E402
    ACTOR_TABLES,
    _applications,
    _fence_rules,
    lane_tables,
)

#: The credential of the hosted tests: inert, and it never leaves the process.
CREDENTIAL = "hosted-test-only-not-a-real-credential"


class TripwireTransport(httpx.BaseTransport):
    """A transport stub that records a call and fails it."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        raise httpx.ConnectError("the tripwire transport must never be reached")


def _seed(settings: Settings) -> None:
    """Create the database of the settings and reset the demonstration."""
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


@pytest.fixture()
def worker_environment(tmp_path: Path) -> Settings:
    """Return settings of a deployment that allows the background worker."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'agent-worker.db'}",
            "ACME_SECRET_KEY": "agent-worker-test-secret-value",
            "ACME_AGENT_WORKER_ENABLED": "true",
        },
        key_file=tmp_path / "missing.env",
    )
    _seed(settings)
    return settings


@pytest.fixture()
def hosted_worker_environment(tmp_path: Path) -> Settings:
    """Return the settings of a hosted deployment with a key and the worker on.

    The provider lock of a hosted deployment is on, so a call would be
    refused.  The worker must not even try to send one.
    """
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'hosted-agent-worker.db'}",
            "ACME_SECRET_KEY": "hosted-agent-worker-test-secret-value",
            "META_API_KEY": CREDENTIAL,
            "ACME_MUSE_PROVIDER_ENABLED": "true",
            "ACME_PUBLIC_DEMO": "true",
            "ACME_AGENT_WORKER_ENABLED": "true",
        },
        key_file=tmp_path / "missing.env",
    )
    _seed(settings)
    return settings


def _administrator(session) -> ActorContext:
    """Return the acting context of the City Administrator."""
    grants = PermissionResolver(session).grants_for("persona_city_administrator")
    return ActorContext(
        actor_id="persona_city_administrator",
        role_ids=frozenset(),
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(record for grant in grants for record in grant.record_scope),
    )


def _automatic(session, runs_per_hour: int = 60) -> None:
    """Switch the City to automatic processing, the way the tab does."""
    ConfigurationService(session).set_processing_policy(
        automatic=True,
        runs_per_hour=runs_per_hour,
        reason="Automatic coverage",
        actor=_administrator(session),
    )


def _wake(session) -> None:
    """Wake the intake agent, the way the operator does."""
    service = AgentControlService(session)
    service.ensure_defaults()
    row = service.state(agent_models.AGENT_INTAKE)
    assert row is not None
    row.mode = agent_models.AGENT_AWAKE
    session.flush()


def _arrival(
    session,
    settings: Settings,
    scenario: str = "deck-high",
    *,
    sequence_start: int = 1,
) -> permit.Application:
    """Return one genuine arrival, submitted through the outside intake."""
    record = build_scenario(scenario, sequence_start=sequence_start)[0]
    from acme_city.portal_intake.service import IntakeService

    result = IntakeService(session, settings=settings).submit_record(
        record, service_actor(session, INTAKE_AGENT_ID)
    )
    assert result.application_id is not None
    application = session.get(permit.Application, result.application_id)
    assert application is not None
    return application


def _outcomes(session) -> dict:
    """Return the outcomes of the controlled data of the demonstration.

    The rules are evaluated in a session that is rolled back, so nothing is
    written by the observation itself.
    """
    try:
        excluded = lane_tables() | ACTOR_TABLES
        return {
            "applications": _applications(session),
            "fence_rules": _fence_rules(session),
            "seeded_row_counts": {
                table: count
                for table, count in sorted(seeded_row_counts(session).items())
                if table not in excluded
            },
        }
    finally:
        session.rollback()


def _controlled(session) -> dict:
    """Return the outcomes of the controlled cases of the demonstration."""
    try:
        return {
            "applications": _applications(session),
            "fence_rules": _fence_rules(session),
        }
    finally:
        session.rollback()


def test_the_worker_does_not_start_with_the_default_settings(tmp_path: Path) -> None:
    """The worker is off unless the deployment asks for it."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'default-worker.db'}",
            "ACME_SECRET_KEY": "default-worker-test-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    assert settings.agent_worker_enabled is False
    _seed(settings)
    app = create_app(settings)
    with TestClient(app) as client:
        assert app.state.agent_worker is None
        assert client.get("/healthz").status_code == 200


def test_the_application_runs_the_worker_while_it_is_up(
    worker_environment: Settings,
) -> None:
    """The service starts one worker and stops it when it shuts down."""
    app = create_app(worker_environment)
    with TestClient(app) as client:
        worker = app.state.agent_worker
        assert worker is not None
        assert worker.running
        assert client.get("/healthz").status_code == 200
    assert not worker.running


def test_the_worker_starts_and_stops_cleanly(worker_environment: Settings) -> None:
    """The loop ends when it is stopped and leaves no thread behind."""
    factory = SessionFactory(worker_environment.database_url)
    try:
        worker = AgentWorker(factory, settings=worker_environment)
        assert not worker.running
        worker.start()
        try:
            assert worker.running
        finally:
            worker.stop()
        assert not worker.running
    finally:
        factory.dispose()


def test_one_worker_cycle_leaves_the_outcomes_unchanged(
    worker_environment: Settings,
) -> None:
    """The worker never touches the controlled fixture of the demonstration."""
    factory = SessionFactory(worker_environment.database_url)
    try:
        with transaction(factory) as session:
            _automatic(session)
        with factory() as session:
            before = _outcomes(session)
        worker = AgentWorker(factory, settings=worker_environment)
        assert worker.run_cycle() == 0
        with factory() as session:
            after = _outcomes(session)
        assert after == before
    finally:
        factory.dispose()


def test_the_cycle_works_an_arrival_with_the_built_in_logic(
    worker_environment: Settings,
) -> None:
    """Without a key the worker works the case with the built in logic."""
    factory = SessionFactory(worker_environment.database_url)
    try:
        with transaction(factory) as session:
            _automatic(session)
            _wake(session)
            application = _arrival(session, worker_environment)
            application_id = application.id
        with factory() as session:
            before = _controlled(session)
        worker = AgentWorker(factory, settings=worker_environment)
        assert worker.run_cycle() == 1
        with factory() as session:
            run = session.execute(
                select(agent_models.AgentRun).where(
                    agent_models.AgentRun.application_id == application_id
                )
            ).scalars().first()
            assert run is not None, "the worker did not work the arrival"
            assert run.triggered_by == WORKER_ACTOR_ID
            assert (run.inputs or {}).get("engine") == "builtin"
            model_run = session.execute(
                select(ModelRun).where(ModelRun.mode == "builtin")
            ).scalars().first()
            assert model_run is not None, "the built in extraction was not recorded"
            work = session.execute(
                select(agent_ops.AgentWorkQueue).where(
                    agent_ops.AgentWorkQueue.application_id == application_id
                )
            ).scalars().first()
            assert work is not None
            assert work.status == agent_ops.WORK_COMPLETED
            # The controlled cases of the demonstration are untouched.
            assert _controlled(session) == before
    finally:
        factory.dispose()


def test_the_cycle_never_calls_the_model_provider(
    hosted_worker_environment: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hosted deployment sends no provider request, whatever the credential."""
    tripwire = TripwireTransport()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", tripwire.handle_request)
    factory = SessionFactory(hosted_worker_environment.database_url)
    try:
        with transaction(factory) as session:
            _automatic(session)
            _wake(session)
            application = _arrival(session, hosted_worker_environment)
            application_id = application.id
        worker = AgentWorker(factory, settings=hosted_worker_environment)
        assert worker.run_cycle() == 1
        assert tripwire.calls == [], "the worker called the provider"
        with factory() as session:
            run = session.execute(
                select(agent_models.AgentRun).where(
                    agent_models.AgentRun.application_id == application_id
                )
            ).scalars().first()
            assert run is not None
            assert (run.inputs or {}).get("engine") == "builtin"
            live = session.execute(
                select(ModelRun).where(ModelRun.mode == "live")
            ).scalars().all()
            assert live == []
    finally:
        factory.dispose()


def test_the_loop_works_an_arrival_without_a_browser(
    worker_environment: Settings,
) -> None:
    """The background loop works the case while nobody is looking."""
    factory = SessionFactory(worker_environment.database_url)
    try:
        with transaction(factory) as session:
            _automatic(session)
            _wake(session)
            application = _arrival(session, worker_environment)
            application_id = application.id
        worker = AgentWorker(factory, settings=worker_environment)
        worker.start()
        try:
            deadline = time.monotonic() + 20.0
            worked = False
            while time.monotonic() < deadline and not worked:
                time.sleep(0.2)
                with factory() as session:
                    worked = (
                        session.execute(
                            select(agent_models.AgentRun).where(
                                agent_models.AgentRun.application_id == application_id
                            )
                        ).scalars().first()
                        is not None
                    )
        finally:
            worker.stop()
        assert worked, "the loop did not work the arrival"
    finally:
        factory.dispose()


def test_the_worker_does_nothing_while_the_policy_is_manual(
    worker_environment: Settings,
) -> None:
    """A manual policy leaves the arrival waiting for a person."""
    factory = SessionFactory(worker_environment.database_url)
    try:
        with transaction(factory) as session:
            application = _arrival(session, worker_environment)
            application_id = application.id
        worker = AgentWorker(factory, settings=worker_environment)
        assert worker.run_cycle() == 0
        with factory() as session:
            runs = session.execute(
                select(agent_models.AgentRun).where(
                    agent_models.AgentRun.application_id == application_id
                )
            ).scalars().all()
            assert runs == []
            queued = session.execute(select(agent_ops.AgentWorkQueue)).scalars().all()
            assert queued == []
    finally:
        factory.dispose()


def test_the_worker_does_nothing_while_the_agent_is_asleep(
    worker_environment: Settings,
) -> None:
    """A sleeping agent is not worked on, even when the policy is automatic."""
    factory = SessionFactory(worker_environment.database_url)
    try:
        with transaction(factory) as session:
            _automatic(session)
            application = _arrival(session, worker_environment)
            application_id = application.id
        # The seeded agent is asleep, so the worker leaves the arrival alone.
        worker = AgentWorker(factory, settings=worker_environment)
        assert worker.run_cycle() == 0
        with factory() as session:
            runs = session.execute(
                select(agent_models.AgentRun).where(
                    agent_models.AgentRun.application_id == application_id
                )
            ).scalars().all()
            assert runs == []
            queued = session.execute(select(agent_ops.AgentWorkQueue)).scalars().all()
            assert queued == []
    finally:
        factory.dispose()


def test_the_worker_never_works_a_case_a_person_already_worked(
    worker_environment: Settings,
) -> None:
    """A case a person worked between the schedule and the work is worked once."""
    factory = SessionFactory(worker_environment.database_url)
    try:
        with transaction(factory) as session:
            _automatic(session)
            _wake(session)
            application = _arrival(session, worker_environment)
            application_id = application.id
        worker = AgentWorker(factory, settings=worker_environment)
        # The worker records the arrival as work and picks it up.
        with transaction(factory) as session:
            work_ids = worker._schedule(session)
        assert len(work_ids) == 1
        # A person works the case in the meantime.
        with transaction(factory) as session:
            application = session.get(permit.Application, application_id)
            assert application is not None
            run_agent(
                session,
                application=application,
                agent_key=agent_models.AGENT_INTAKE,
                triggered_by="persona_agent_operator",
                settings=worker_environment,
            )
        # The worker leaves the finished work alone.
        assert worker._work(work_ids[0]) == 0
        with factory() as session:
            runs = session.execute(
                select(agent_models.AgentRun).where(
                    agent_models.AgentRun.application_id == application_id
                )
            ).scalars().all()
            assert len(runs) == 1, "the case was worked twice"
            work = session.execute(
                select(agent_ops.AgentWorkQueue).where(
                    agent_ops.AgentWorkQueue.application_id == application_id
                )
            ).scalars().first()
            assert work is not None
            assert work.status == agent_ops.WORK_COMPLETED
            assert work.attempts == 1
    finally:
        factory.dispose()


def test_the_worker_stops_at_the_hourly_limit(worker_environment: Settings) -> None:
    """The worker works as many cases as the hour allows, and no more."""
    factory = SessionFactory(worker_environment.database_url)
    try:
        with transaction(factory) as session:
            _automatic(session, runs_per_hour=1)
            _wake(session)
            first = _arrival(session, worker_environment)
            second = _arrival(session, worker_environment, sequence_start=2)
            application_ids = [first.id, second.id]
        worker = AgentWorker(factory, settings=worker_environment)
        assert worker.run_cycle() == 1
        # The hour holds one run, so the second cycle works nothing.
        assert worker.run_cycle() == 0
        with factory() as session:
            runs = session.execute(
                select(agent_models.AgentRun).where(
                    agent_models.AgentRun.application_id.in_(application_ids)
                )
            ).scalars().all()
            assert len(runs) == 1
    finally:
        factory.dispose()
