"""The steward assistant on the screens of the Data Steward.

The tests walk the queue and one task as the Data Steward: the button that
prepares the work of the queue, the button that prepares the work of one
task, the evidence panel and the acceptance of a recommendation.  The
recommendation is accepted through the existing service of the task kind, with
the steward as the decider of record, and the recommendation is recorded in
the audit trail.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, PER-04, SEC-01

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.agents.control import AgentControlService
from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.models import audit, change, registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

#: The source record the demonstration compares with the master records.
RECORD = "PER-AP-0003"


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'steward-assist-ui.db'}",
            "ACME_SECRET_KEY": "steward-assist-ui-secret-value",
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


def wake_the_assistant(client: TestClient) -> None:
    """Wake the steward assistant, the way the Agent Operator does."""
    choose(client, "persona_agent_operator")
    response = client.post(
        "/ui/actions/agent.toggle",
        data={
            "csrf_token": csrf(client, "/agent/steward_assist"),
            "next": "/agent/steward_assist",
            "agent_key": "steward_assist",
            "mode": "awake",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"
    choose(client, "persona_data_steward")


def case_path(client: TestClient, record: str = RECORD) -> str:
    """Return the address of the focused case of one source record."""
    queue = client.get("/steward?filter=needs_review").text
    for href in re.findall(r'href="(/steward/issues/link/[^"]+)"', queue):
        if record in client.get(href).text.split("<h1", 1)[1][:400]:
            return href
    raise AssertionError(f"no task for {record}")


def task_id(path: str) -> str:
    """Return the identifier of the task the case is about."""
    return path.split("?", 1)[0].rsplit("/", 1)[-1]


def recommendation_of(client: TestClient, path: str) -> str:
    """Return the identifier of the recommendation the case shows."""
    html = client.get(path).text
    match = re.search(r'name="recommendation_id" value="([^"]+)"', html)
    assert match, html[:400]
    return match.group(1)


def stored_recommendations(environment: Settings) -> list[StewardRecommendation]:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            return list(
                session.execute(
                    select(StewardRecommendation).order_by(StewardRecommendation.made_at)
                ).scalars().all()
            )
    finally:
        factory.dispose()


def crosswalk_of(environment: Settings, record: str = RECORD):
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            return list(
                session.execute(
                    select(registry.Crosswalk)
                    .where(registry.Crosswalk.source_record_id == record)
                    .order_by(registry.Crosswalk.created_at)
                ).scalars().all()
            )
    finally:
        factory.dispose()


def raise_correction(environment: Settings) -> str:
    """Raise a correction of a source record and return its identifier."""
    from acme_city.auth.context import ActorContext
    from acme_city.changes.schemas import ChangeRequestCommand
    from acme_city.changes.service import ChangeService

    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            view = ChangeService(session).request(
                ChangeRequestCommand(
                    target_type="source_record",
                    target_id="gis/address_register/GIS-AD-0400",
                    title="A fictional correction of an official address",
                    reason="the demonstration corrects a fictional official address",
                    proposed_value={"address_line_1": "400 Lantern Row"},
                    old_value={},
                ),
                ActorContext(actor_id="persona_data_steward", role_ids=frozenset()),
            )
            return view.change_case_id
    finally:
        factory.dispose()


def decide_on_the_link(environment: Settings, record: str = RECORD) -> None:
    """Let the steward decide on the link of the source record."""
    from acme_city.auth.context import ActorContext
    from acme_city.registry.schemas import MatchDecisionCommand
    from acme_city.registry.service import RegistryService

    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            service = RegistryService(session)
            crosswalk = service.open_crosswalk("permitting", record)
            assert crosswalk is not None
            service.decide(
                MatchDecisionCommand(
                    decision="reject",
                    reason="the demonstration steward rejects the link",
                    source_system_id="permitting",
                    dataset_key="applicant_profiles",
                    source_record_id=record,
                    crosswalk_id=crosswalk.id,
                    expected_version=crosswalk.version,
                ),
                ActorContext(actor_id="persona_data_steward", role_ids=frozenset()),
            )
    finally:
        factory.dispose()


# ------------------------------------------------------------------ the queue


def test_the_queue_offers_the_prepare_button_to_the_steward(
    client: TestClient, environment: Settings
) -> None:
    """The button is there, and it says that the assistant sleeps."""
    choose(client, "persona_data_steward")
    body = client.get("/steward").text
    assert 'data-testid="assistant-prepare"' in body
    assert 'data-testid="assistant-sleep-note"' in body
    assert "Press Wake to wake it" in body


def test_the_prepare_button_is_off_while_the_assistant_sleeps(
    client: TestClient, environment: Settings
) -> None:
    """A sleeping assistant prepares nothing, and the button says why."""
    choose(client, "persona_data_steward")
    body = client.get("/steward").text
    button = re.search(r'<button[^>]*data-testid="assistant-prepare"[^>]*>', body)
    assert button is not None
    assert "disabled" in button.group(0)


def test_the_operator_may_prepare_the_recommendations(
    client: TestClient, environment: Settings
) -> None:
    """The operator wakes the assistant and asks it to prepare the work."""
    wake_the_assistant(client)
    choose(client, "persona_agent_operator")
    response = post(
        client,
        "steward.assist.prepare",
        {"next": "/agent/steward_assist"},
        "/agent/steward_assist",
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"
    stored = stored_recommendations(environment)
    assert stored, "the press recorded a recommendation"


def test_the_operator_may_not_accept_a_recommendation(
    client: TestClient, environment: Settings
) -> None:
    """The operator prepares the work; the Data Steward decides it."""
    wake_the_assistant(client)
    choose(client, "persona_agent_operator")
    post(
        client,
        "steward.assist.prepare",
        {"next": "/agent/steward_assist"},
        "/agent/steward_assist",
    )
    stored = stored_recommendations(environment)
    assert stored, "the press recorded a recommendation"
    response = post(
        client,
        "steward.assist.accept",
        {"next": "/agent/steward_assist", "recommendation_id": stored[0].id},
        "/agent/steward_assist",
    )
    assert response.status_code == 403, response.text
    assert response.json()["status"] == "denied"


def test_a_press_prepares_the_recommendations_of_the_queue(
    client: TestClient, environment: Settings
) -> None:
    """One press prepares the work of the tasks and the queue shows it."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    response = post(
        client,
        "steward.assist.prepare",
        {"next": "/steward"},
        "/steward",
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"
    stored = stored_recommendations(environment)
    assert stored, "the press recorded a recommendation"
    body = client.get("/steward").text
    assert 'data-testid="recommendation-pill"' in body
    assert 'data-testid="recommendation-reason"' in body
    pills = set(re.findall(r'data-testid="recommendation-pill">([^<]+)<', body))
    assert pills <= {"High", "Review", "Held"}


def test_the_run_of_a_press_shows_in_the_run_history(
    client: TestClient, environment: Settings
) -> None:
    """The operator reads what the assistant did in the run history."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    post(client, "steward.assist.prepare", {"next": "/steward"}, "/steward")
    choose(client, "persona_agent_operator")
    body = client.get("/agents/runs?agent_key=steward_assist").text
    assert 'data-testid="agent-run-row"' in body
    assert "Steward assistant" in body
    # The run names the persona that asked for the work.
    assert "Data Steward" in body


def test_the_prepare_button_is_off_for_a_persona_without_the_grant(
    client: TestClient, environment: Settings
) -> None:
    """The queue of the Permit Reviewer does not carry the button."""
    choose(client, "persona_permit_reviewer")
    response = client.get("/steward")
    assert response.status_code == 403


# --------------------------------------------------------------- the task page


def test_the_task_page_carries_the_button_of_the_assistant(
    client: TestClient, environment: Settings
) -> None:
    """The task shows the button that prepares its recommendation."""
    choose(client, "persona_data_steward")
    path = case_path(client)
    body = client.get(path).text
    assert 'data-testid="assistant-panel"' in body
    assert 'data-testid="assistant-recommend"' in body
    assert 'data-testid="assistant-empty"' in body


def test_the_task_page_shows_the_evidence_of_the_recommendation(
    client: TestClient, environment: Settings
) -> None:
    """The panel shows the facts the assistant read."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    path = case_path(client)
    response = post(
        client,
        "steward.assist.recommend",
        {
            "task_kind": "link",
            "task_id": task_id(path),
            "next": path,
        },
        path,
    )
    assert response.status_code == 200, response.text
    body = client.get(path).text
    assert 'data-testid="assistant-pill"' in body
    assert 'data-testid="assistant-reason"' in body
    assert 'data-testid="assistant-evidence"' in body
    assert 'data-testid="assistant-accept"' in body
    # The reason is prefilled and editable.
    field = re.search(
        r'<textarea[^>]*data-testid="assistant-reason-field"[^>]*>(.*?)</textarea>',
        body,
        re.S,
    )
    assert field is not None
    assert field.group(1).strip()


def test_accepting_a_recommendation_writes_through_the_existing_service(
    client: TestClient, environment: Settings
) -> None:
    """The steward decides, the service of the City writes, the trail names it."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    path = case_path(client)
    post(
        client,
        "steward.assist.recommend",
        {"task_kind": "link", "task_id": task_id(path), "next": path},
        path,
    )
    identifier = recommendation_of(client, path)
    response = post(
        client,
        "steward.assist.accept",
        {"recommendation_id": identifier, "reason": "the evidence agrees", "next": path},
        path,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"

    # The link of the source record is approved by the steward.
    links = crosswalk_of(environment)
    assert links[-1].link_status == "approved"
    assert links[-1].decision_actor_id == "persona_data_steward"
    assert links[-1].decision == "the evidence agrees"

    # The audit trail names the recommendation.
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "steward.recommendation.accept"
                )
            ).scalars().all()
            assert len(events) == 1
            assert identifier in events[0].references
            assert events[0].actor_id == "persona_data_steward"
    finally:
        factory.dispose()

    # The recommendation is cleared, so the task holds no answer twice.
    body = client.get(path).text
    assert 'data-testid="assistant-empty"' in body


def test_accepting_a_correction_moves_the_case_through_the_change_service(
    client: TestClient, environment: Settings
) -> None:
    """A correction is accepted through the service that moves a change case."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    case_id = raise_correction(environment)
    path = f"/steward/issues/case/{case_id}"
    response = post(
        client,
        "steward.assist.recommend",
        {"task_kind": "case", "task_id": case_id, "next": path},
        path,
    )
    assert response.status_code == 200, response.text
    identifier = recommendation_of(client, path)
    response = post(
        client,
        "steward.assist.accept",
        {"recommendation_id": identifier, "reason": "the value is right", "next": path},
        path,
    )
    assert response.status_code == 200, response.text
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.get(change.ChangeCase, case_id)
            assert row is not None
            assert row.status == "in_review"
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "steward.recommendation.accept"
                )
            ).scalars().all()
            assert len(events) == 1
            assert identifier in events[0].references
            assert events[0].actor_id == "persona_data_steward"
    finally:
        factory.dispose()


def test_a_persona_without_the_grant_may_not_accept_a_recommendation(
    client: TestClient, environment: Settings
) -> None:
    """The City Administrator may read the queue, but the recommendation is the steward's."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    path = case_path(client)
    post(
        client,
        "steward.assist.recommend",
        {"task_kind": "link", "task_id": task_id(path), "next": path},
        path,
    )
    identifier = recommendation_of(client, path)
    choose(client, "persona_city_administrator")
    response = post(
        client,
        "steward.assist.accept",
        {"recommendation_id": identifier, "reason": "the evidence agrees", "next": path},
        path,
    )
    assert response.status_code == 403, response.text
    assert crosswalk_of(environment)[-1].link_status != "approved"


def test_a_held_recommendation_is_never_accepted(
    client: TestClient, environment: Settings
) -> None:
    """A recommendation held for a person is read, not accepted."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    path = case_path(client)
    post(
        client,
        "steward.assist.recommend",
        {"task_kind": "link", "task_id": task_id(path), "next": path},
        path,
    )
    identifier = recommendation_of(client, path)
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, identifier)
            assert row is not None
            row.confidence = "held"
    finally:
        factory.dispose()
    response = post(
        client,
        "steward.assist.accept",
        {"recommendation_id": identifier, "reason": "the evidence agrees", "next": path},
        path,
    )
    assert response.status_code == 422, response.text
    assert response.json()["message"] == "Held: decide this one yourself."
    assert crosswalk_of(environment)[-1].link_status != "approved"


def test_the_held_button_is_off_and_says_who_decides(
    client: TestClient, environment: Settings
) -> None:
    """The button is off, and the note beside it says who decides."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    path = case_path(client)
    post(
        client,
        "steward.assist.recommend",
        {"task_kind": "link", "task_id": task_id(path), "next": path},
        path,
    )
    identifier = recommendation_of(client, path)
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, identifier)
            assert row is not None
            row.confidence = "held"
    finally:
        factory.dispose()
    body = client.get(path).text
    button = re.search(r'<button[^>]*data-testid="assistant-accept"[^>]*>', body)
    assert button is not None
    assert "disabled" in button.group(0)
    note = re.search(r'data-testid="assistant-accept-note">(.*?)</p>', body, flags=re.S)
    assert note is not None
    assert " ".join(note.group(1).split()) == "Held: decide this one yourself."


def test_the_stale_button_is_off_and_names_the_button_that_fixes_it(
    client: TestClient, environment: Settings
) -> None:
    """The button is off, and the note says to ask for the recommendation again."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    path = case_path(client)
    post(
        client,
        "steward.assist.recommend",
        {"task_kind": "link", "task_id": task_id(path), "next": path},
        path,
    )
    identifier = recommendation_of(client, path)
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            party = session.get(registry.Party, "party_cedarline")
            assert party is not None
            party.version += 1
    finally:
        factory.dispose()
    body = client.get(path).text
    button = re.search(r'<button[^>]*data-testid="assistant-accept"[^>]*>', body)
    assert button is not None
    assert "disabled" in button.group(0)
    note = re.search(r'data-testid="assistant-accept-note">(.*?)</p>', body, flags=re.S)
    assert note is not None
    assert " ".join(note.group(1).split()) == (
        "This record changed since the recommendation; press Get recommendation again."
    )
    # The note names a button, so the button carries that label.
    prepare = re.search(
        r'data-testid="assistant-recommend".*?>\s*(.*?)\s*</button>', body, flags=re.S
    )
    assert prepare is not None
    assert prepare.group(1) == "Get recommendation again"


def test_a_refused_acceptance_shows_the_reason_in_the_feedback_area(
    client: TestClient, environment: Settings
) -> None:
    """The page the steward came from carries the reason of the refusal."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    path = case_path(client)
    post(
        client,
        "steward.assist.recommend",
        {"task_kind": "link", "task_id": task_id(path), "next": path},
        path,
    )
    identifier = recommendation_of(client, path)
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, identifier)
            assert row is not None
            row.confidence = "held"
    finally:
        factory.dispose()
    response = client.post(
        "/ui/actions/steward.assist.accept",
        data={
            "csrf_token": csrf(client, path),
            "action_id": "steward.assist.accept",
            "next": path,
            "recommendation_id": identifier,
        },
        follow_redirects=False,
    )
    # The page the work is on is read again, and the refusal is reported in
    # the feedback region of that page.
    assert response.status_code == 303, response.text
    assert response.headers["location"] == path
    body = client.get(path).text
    outcome = re.search(r'data-testid="feedback" data-outcome="([^"]*)"', body)
    assert outcome is not None
    assert outcome.group(1) == "denied"
    message = re.search(r'data-testid="feedback-message">([^<]*)<', body)
    assert message is not None
    assert message.group(1) == "Held: decide this one yourself."


def test_a_stale_recommendation_is_never_accepted(
    client: TestClient, environment: Settings
) -> None:
    """A record that changed since the recommendation refuses it."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    path = case_path(client)
    post(
        client,
        "steward.assist.recommend",
        {"task_kind": "link", "task_id": task_id(path), "next": path},
        path,
    )
    identifier = recommendation_of(client, path)
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            party = session.get(registry.Party, "party_cedarline")
            assert party is not None
            party.version += 1
    finally:
        factory.dispose()
    response = post(
        client,
        "steward.assist.accept",
        {"recommendation_id": identifier, "reason": "the evidence agrees", "next": path},
        path,
    )
    assert response.status_code == 422, response.text
    assert response.json()["message"] == (
        "This record changed since the recommendation; press Get recommendation again."
    )
    assert crosswalk_of(environment)[-1].link_status != "approved"


def test_a_link_decided_since_the_recommendation_is_never_accepted(
    client: TestClient, environment: Settings
) -> None:
    """A link that was decided since the recommendation refuses it."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    path = case_path(client)
    post(
        client,
        "steward.assist.recommend",
        {"task_kind": "link", "task_id": task_id(path), "next": path},
        path,
    )
    identifier = recommendation_of(client, path)
    # Another steward decides on the link through the ordinary control.
    decide_on_the_link(environment)
    response = post(
        client,
        "steward.assist.accept",
        {"recommendation_id": identifier, "reason": "the evidence agrees", "next": path},
        path,
    )
    assert response.status_code == 422, response.text
    assert response.json()["message"] == (
        "This record changed since the recommendation; press Get recommendation again."
    )
    assert crosswalk_of(environment)[-1].link_status != "approved"


def test_the_steward_can_clear_a_recommendation(
    client: TestClient, environment: Settings
) -> None:
    """A recommendation the steward does not want is cleared."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    path = case_path(client)
    post(
        client,
        "steward.assist.recommend",
        {"task_kind": "link", "task_id": task_id(path), "next": path},
        path,
    )
    response = post(
        client,
        "steward.assist.clear",
        {"task_kind": "link", "task_id": task_id(path), "next": path},
        path,
    )
    assert response.status_code == 200, response.text
    body = client.get(path).text
    assert 'data-testid="assistant-empty"' in body
    assert all(row.cleared for row in stored_recommendations(environment))


def test_the_assistant_sleeps_again_and_the_recommendation_stays(
    client: TestClient, environment: Settings
) -> None:
    """Putting the assistant to sleep stops new work, not the reading."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    path = case_path(client)
    post(
        client,
        "steward.assist.recommend",
        {"task_kind": "link", "task_id": task_id(path), "next": path},
        path,
    )
    # The Agent Operator puts the assistant back to sleep.
    choose(client, "persona_agent_operator")
    client.post(
        "/ui/actions/agent.toggle",
        data={
            "csrf_token": csrf(client, "/agent/steward_assist"),
            "next": "/agent/steward_assist",
            "agent_key": "steward_assist",
            "mode": "asleep",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    choose(client, "persona_data_steward")
    body = client.get(path).text
    # The recommendation stays visible and says that it was made while awake.
    assert 'data-testid="assistant-pill"' in body
    assert 'data-testid="assistant-awake-note"' in body
    assert "Made while awake" in body
    # The button that asks for new work is off.
    button = re.search(r'<button[^>]*data-testid="assistant-recommend"[^>]*>', body)
    assert button is not None
    assert "disabled" in button.group(0)


# ----------------------------------------------- the steward's own wake switch


def toggle_events(environment: Settings, outcome: str = "accepted") -> list[audit.AuditEvent]:
    action = "agent.toggle" if outcome == "accepted" else "ui.agent.toggle"
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            return list(
                session.execute(
                    select(audit.AuditEvent)
                    .where(audit.AuditEvent.action == action)
                    .where(audit.AuditEvent.outcome == outcome)
                ).scalars().all()
            )
    finally:
        factory.dispose()


def steward_toggle(client: TestClient, agent_key: str, mode: str):
    return post(client, "agent.toggle", {"agent_key": agent_key, "mode": mode}, "/steward")


def test_the_steward_wakes_and_sleeps_the_assistant_from_data_issues(
    client: TestClient, environment: Settings
) -> None:
    """The home of the steward shows the state and the switch; the audit names the steward."""
    choose(client, "persona_data_steward")
    body = client.get("/steward").text
    assert 'data-testid="assistant-mode"' in body
    assert "asleep" in body.split('data-testid="assistant-mode"', 1)[1][:40]
    assert 'data-testid="assistant-toggle"' in body
    assert ">Wake<" in body

    woken = steward_toggle(client, "steward_assist", "awake")
    assert woken.status_code == 200, woken.text
    body = client.get("/steward").text
    assert "awake" in body.split('data-testid="assistant-mode"', 1)[1][:40]
    assert ">Put to sleep<" in body
    button = re.search(r'<button[^>]*data-testid="assistant-prepare"[^>]*>', body)
    assert button is not None and "disabled" not in button.group(0)

    slept = steward_toggle(client, "steward_assist", "asleep")
    assert slept.status_code == 200, slept.text
    assert "asleep" in client.get("/steward").text.split('data-testid="assistant-mode"', 1)[1][:40]

    events = toggle_events(environment)
    assert [event.actor_id for event in events] == ["persona_data_steward"] * 2
    assert [event.metadata_json["after"] for event in events] == ["awake", "asleep"]
    assert all(event.metadata_json["agent_key"] == "steward_assist" for event in events)


def test_the_steward_cannot_wake_the_intake_or_adjudication_agent(
    client: TestClient, environment: Settings
) -> None:
    """The scoped grant covers the steward assistant and no other agent."""
    choose(client, "persona_data_steward")
    for agent_key in ("intake", "adjudication"):
        response = steward_toggle(client, agent_key, "awake")
        assert response.status_code == 403, response.text
        assert response.json()["status"] == "denied"
    assert toggle_events(environment) == []
    assert len(toggle_events(environment, outcome="denied")) == 2
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            from acme_city.agents.control import is_awake

            assert not is_awake(session, "intake")
            assert not is_awake(session, "adjudication")
    finally:
        factory.dispose()


def test_the_operator_still_wakes_every_agent(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_agent_operator")
    for agent_key in ("intake", "adjudication", "steward_assist"):
        response = post(
            client,
            "agent.toggle",
            {"agent_key": agent_key, "mode": "awake"},
            f"/agent/{agent_key}",
        )
        assert response.status_code == 200, response.text
    assert {e.metadata_json["agent_key"] for e in toggle_events(environment)} == {
        "intake",
        "adjudication",
        "steward_assist",
    }


def test_a_persona_without_the_switch_is_refused(client: TestClient) -> None:
    choose(client, "persona_permit_reviewer")
    response = post(
        client, "agent.toggle", {"agent_key": "steward_assist", "mode": "awake"}, "/queue/intake"
    )
    assert response.status_code == 403, response.text
