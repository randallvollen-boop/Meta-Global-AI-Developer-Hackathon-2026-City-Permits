"""The steward assistant accepts a recommendation of every kind of task.

Each test walks the flow a Data Steward walks: the assistant prepares the
work of a task, the steward reads the evidence and accepts the
recommendation, and the existing service of the City writes as it always
does.  The decision of record is the steward's, and the trail names the
recommendation that was accepted.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, PER-04, SEC-01, MDM-02

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.agents.control import AgentControlService
from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_assist_demo import seed_steward_assistant_demo
from acme_city.fixtures.steward_automation_demo import seed_automation
from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.gis.adapter import LocatorCandidate, ParcelRecord
from acme_city.gis.matching import ParcelMatchService
from acme_city.persistence.models import audit, change, permit, registry, registry_automation
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

STEWARD = ActorContext(
    actor_id="persona_data_steward", role_ids=frozenset({"domain_steward"})
)
OPERATOR = ActorContext(
    actor_id="persona_agent_operator", role_ids=frozenset({"agent_operator"})
)

#: The candidates the fictional locator of the tests answers with.
CANDIDATES = (
    LocatorCandidate(
        address="400 Lantern Row",
        x=100.0,
        y=200.0,
        score=95.0,
        status="M",
        address_id="GIS-AD-0400",
    ),
)

#: The parcels the fictional locator of the tests answers with.
PARCELS = {
    (100.0, 200.0): ParcelRecord(
        parcel_number="ACME-P-1001", site_address="400 Lantern Row"
    ),
}


class FictionalLocator:
    """A locator that answers with the fictional parcels of the demonstration."""

    def __init__(self) -> None:
        self._candidates = CANDIDATES
        self._parcels = PARCELS

    @property
    def source_label(self) -> str:
        return "ACME GIS (fictional locator of the test)"

    def find_candidates(self, text: str, max_locations: int = 5) -> list[LocatorCandidate]:
        return list(self._candidates[:max_locations])

    def parcel_at(self, x: float, y: float) -> ParcelRecord | None:
        return self._parcels.get((x, y))


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'steward-acceptance.db'}",
            "ACME_SECRET_KEY": "steward-acceptance-secret-value",
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
        with transaction(factory) as session:
            seed_cedarline(session)
            seed_automation(session)
            seed_steward_assistant_demo(session, bundle)
    finally:
        factory.dispose()
    return settings


@pytest.fixture()
def client(environment: Settings) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def csrf(client: TestClient, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def post(client: TestClient, action: str, fields: dict[str, str], next_path: str):
    return client.post(
        f"/ui/actions/{action}",
        data={"csrf_token": csrf(client, next_path), "next": next_path, **fields},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


def wake_the_assistant(environment: Settings) -> None:
    """Wake the steward assistant, the way the Agent Operator does."""
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            AgentControlService(session).set_mode("steward_assist", "awake", OPERATOR)
    finally:
        factory.dispose()


def task_path(client: TestClient, kind: str) -> str:
    """Return the address of the focused case of one kind of task."""
    queue = client.get("/steward?filter=needs_review").text
    hrefs = re.findall(rf'href="(/steward/issues/{kind}/[^"]+)"', queue)
    assert hrefs, f"the queue holds no {kind} task"
    return hrefs[0]


def prepare_and_accept(
    client: TestClient, environment: Settings, kind: str
) -> str:
    """Prepare the recommendation of one task and accept it."""
    wake_the_assistant(environment)
    choose(client, "persona_data_steward")
    path = task_path(client, kind)
    task_id = path.split("?")[0].rsplit("/", 1)[-1]
    response = post(
        client,
        "steward.assist.recommend",
        {"task_kind": kind, "task_id": task_id, "next": path},
        path,
    )
    assert response.status_code == 200, response.text
    body = client.get(path).text
    identifier = re.search(r'name="recommendation_id" value="([^"]+)"', body)
    assert identifier is not None, body[:400]
    response = post(
        client,
        "steward.assist.accept",
        {"recommendation_id": identifier.group(1), "reason": "the evidence agrees"},
        path,
    )
    assert response.status_code == 200, response.text
    return identifier.group(1)


def accept_events(environment: Settings) -> list[audit.AuditEvent]:
    """Return the recorded decisions of the steward."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            return list(
                session.execute(
                    select(audit.AuditEvent).where(
                        audit.AuditEvent.action == "steward.recommendation.accept"
                    )
                ).scalars()
            )
    finally:
        factory.dispose()


# ------------------------------------------------------------- the record match


def test_a_record_match_is_accepted_through_the_service(
    client: TestClient, environment: Settings
) -> None:
    """The steward confirms a link; the registry writes it."""
    identifier = prepare_and_accept(client, environment, "link")
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            links = session.execute(select(registry.Crosswalk)).scalars().all()
            decided = [
                link for link in links if link.decision_actor_id == "persona_data_steward"
            ]
            assert decided
            assert decided[-1].link_status == "approved"
    finally:
        factory.dispose()
    events = accept_events(environment)
    assert len(events) == 1
    assert identifier in (events[0].references or [])
    assert events[0].actor_id == "persona_data_steward"


# ---------------------------------------------------------- the applied link


def test_an_applied_link_is_accepted_through_the_service(
    client: TestClient, environment: Settings
) -> None:
    """The steward keeps a link the automation applied."""
    identifier = prepare_and_accept(client, environment, "automatic_link")
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(registry_automation.RegistryAutomationApplication)
            ).scalars().all()
            acknowledged = [row for row in rows if row.status == "acknowledged"]
            assert acknowledged
            assert acknowledged[-1].reviewed_by_actor_id == "persona_data_steward"
    finally:
        factory.dispose()
    events = accept_events(environment)
    assert len(events) == 1
    assert identifier in (events[0].references or [])


# --------------------------------------------------------------- the property


def test_a_property_link_is_accepted_through_the_service(
    client: TestClient, environment: Settings
) -> None:
    """The steward approves a parcel link; the parcel service writes it."""
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(permit.Application, "app_synth_001")
            assert application is not None
            service = ParcelMatchService(
                session, settings=None, locator=FictionalLocator()
            )
            service.locate(application, STEWARD)
    finally:
        factory.dispose()

    identifier = prepare_and_accept(client, environment, "parcel")
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            from acme_city.persistence.models import gis

            match = session.execute(
                select(gis.ApplicationParcelMatch).where(
                    gis.ApplicationParcelMatch.application_id == "app_synth_001"
                )
            ).scalars().first()
            assert match is not None
            assert match.link_state == "approved"
    finally:
        factory.dispose()
    events = accept_events(environment)
    assert len(events) == 1
    assert identifier in (events[0].references or [])


# ------------------------------------------------------------- the correction


def test_a_correction_is_accepted_through_the_service(
    client: TestClient, environment: Settings
) -> None:
    """The steward accepts a correction; the change service moves the case."""
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            from acme_city.changes.schemas import ChangeRequestCommand
            from acme_city.changes.service import ChangeService

            view = ChangeService(session).request(
                ChangeRequestCommand(
                    target_type="source_record",
                    target_id="gis/address_register/GIS-AD-0400",
                    title="A fictional correction of an official address",
                    reason="the demonstration corrects a fictional official address",
                    proposed_value={"address_line_1": "400 Lantern Row"},
                    old_value={},
                ),
                STEWARD,
            )
            case_id = view.change_case_id
    finally:
        factory.dispose()

    identifier = prepare_and_accept(client, environment, "case")
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.get(change.ChangeCase, case_id)
            assert row is not None
            assert row.status == "in_review"
    finally:
        factory.dispose()
    events = accept_events(environment)
    assert len(events) == 1
    assert identifier in (events[0].references or [])


# -------------------------------------------------------------- the data issue


def test_a_data_issue_is_prepared_and_read_but_never_accepted(
    client: TestClient, environment: Settings
) -> None:
    """A data issue has no service action, so the assistant never accepts it."""
    wake_the_assistant(environment)
    choose(client, "persona_data_steward")
    path = task_path(client, "issue")
    task_id = path.split("?")[0].rsplit("/", 1)[-1]
    response = post(
        client,
        "steward.assist.recommend",
        {"task_kind": "issue", "task_id": task_id, "next": path},
        path,
    )
    assert response.status_code == 200, response.text
    body = client.get(path).text
    assert 'data-testid="assistant-pill"' in body
    assert 'data-testid="assistant-reason"' in body
    identifier = re.search(r'name="recommendation_id" value="([^"]+)"', body)
    assert identifier is not None
    # The assistant has no action of its own for a data issue.
    response = post(
        client,
        "steward.assist.accept",
        {"recommendation_id": identifier.group(1), "reason": "the evidence agrees"},
        path,
    )
    assert response.status_code == 422, response.text
    assert accept_events(environment) == []
