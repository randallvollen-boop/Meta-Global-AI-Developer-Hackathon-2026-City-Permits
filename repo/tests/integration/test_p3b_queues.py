"""The three queues of parity phase 3b, through the browser interface.

Each new screen is opened by a grant only its persona holds: the intake
queue and the early-resolution board belong to the Data Steward, the review
queue to the Permit Reviewer.  The bulk action is a governed action: it
checks the grant, the CSRF token and the version of every case it names,
and it either processes the whole selection or none of it.
"""
# REQUIRES: UX-01, UX-02, PER-03, AI-03, SEC-02
# The authorized persona opens each queue, the other personas are refused,
# the tabs hold their exact membership, and the bulk action is a governed
# all-or-nothing write.

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.router import router as permit_router
from acme_city.ui.router import router as ui_router

FACTS = {
    "valuation": "50000.00",
    "valuation_cents": 5000000,
    "project_description": "A fictional fence at 400 Lantern Row",
    "contractor_license": "ACME-LIC-1042",
    "submitted_parcel": "ACME-P-1001",
    "submitted_site_text": "400 Lantern Row, ACME City",
    "channel": "portal",
}


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'p3b-queues.db'}",
            "ACME_SECRET_KEY": "p3b-queue-test-secret-value",
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
def client(environment: Settings) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    app.include_router(permit_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def token(client: TestClient, path: str) -> str:
    """Return the CSRF token of the session from a screen the persona may open."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, f"no CSRF token on {path}"
    return match.group(1)


def submit_arrival(client: TestClient) -> dict:
    """Submit one case that arrived from outside the City."""
    response = client.post(
        "/api/permits/applications",
        json={
            "permit_type_key": "com_ti",
            "facts": dict(FACTS),
            "applicant_party_id": "party_cedarline",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "application_id": body["application_id"],
        "reference": body["source_application_number"],
        "version": body["application_version"],
    }


def submit_arrival_as_steward(client: TestClient) -> dict:
    """Submit one case as the persona that may submit it."""
    choose(client, "persona_data_steward")
    return submit_arrival(client)


def wake_the_agent(environment: Settings) -> None:
    """Wake the intake agent."""
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            row = session.execute(
                select(agent_models.AgentControl).where(
                    agent_models.AgentControl.agent_key == agent_models.AGENT_INTAKE
                )
            ).scalar_one()
            row.mode = agent_models.AGENT_AWAKE
    finally:
        factory.dispose()


def intake_run_count(environment: Settings) -> int:
    """Count the recorded intake runs."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(agent_models.AgentRun).where(
                    agent_models.AgentRun.agent_key == agent_models.AGENT_INTAKE
                )
            ).scalars().all()
            return len(rows)
    finally:
        factory.dispose()


def test_the_data_steward_opens_the_intake_queue(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    response = client.get("/queue/intake")
    assert response.status_code == 200, response.text
    assert "Intake queue" in response.text
    assert 'data-testid="intake-tabs"' in response.text
    assert 'data-testid="intake-table"' in response.text


def test_the_data_steward_opens_the_early_resolution_board(
    client: TestClient,
) -> None:
    choose(client, "persona_data_steward")
    response = client.get("/queue/early-resolution")
    assert response.status_code == 200, response.text
    assert "Early resolution" in response.text
    assert 'data-testid="early-resolution-kpis"' in response.text


def test_the_permit_reviewer_opens_the_review_queue(client: TestClient) -> None:
    choose(client, "persona_permit_reviewer")
    response = client.get("/queue/review")
    assert response.status_code == 200, response.text
    assert "Review queue" in response.text
    assert 'data-testid="review-table"' in response.text
    assert 'data-testid="recent-decisions"' in response.text


@pytest.mark.parametrize(
    ("actor_id", "path"),
    (
        ("persona_applicant", "/queue/intake"),
        ("persona_applicant", "/queue/early-resolution"),
        ("persona_applicant", "/queue/review"),
        ("persona_permit_reviewer", "/queue/early-resolution"),
        ("persona_data_steward", "/queue/review"),
        ("persona_city_administrator", "/queue/early-resolution"),
        ("persona_city_administrator", "/queue/review"),
    ),
)
def test_a_queue_outside_the_grants_is_refused(
    client: TestClient, actor_id: str, path: str
) -> None:
    choose(client, actor_id)
    response = client.get(path)
    assert response.status_code == 403, (actor_id, path)


def test_the_shared_work_queue_links_the_queues_of_the_persona(
    client: TestClient,
) -> None:
    choose(client, "persona_data_steward")
    steward_links = client.get("/queue").text
    assert 'data-queue="intake_queue"' in steward_links
    assert 'data-queue="early_resolution"' in steward_links
    assert 'data-queue="review_queue"' not in steward_links

    choose(client, "persona_permit_reviewer")
    reviewer_links = client.get("/queue").text
    assert 'data-queue="review_queue"' in reviewer_links
    # OPR-3: the reviewer keeps read access to the intake queue (no run grants).
    assert 'data-queue="intake_queue"' in reviewer_links
    assert 'data-queue="early_resolution"' not in reviewer_links

    choose(client, "persona_applicant")
    applicant_links = client.get("/queue").text
    assert 'data-testid="saved-queues"' not in applicant_links


def test_the_tabs_of_the_intake_queue_hold_their_cases(
    client: TestClient, environment: Settings
) -> None:
    choose(client, "persona_data_steward")
    arrival = submit_arrival(client)
    active = client.get("/queue/intake?tab=active")
    assert active.status_code == 200, active.text
    assert arrival["reference"] in active.text
    awaiting = client.get("/queue/intake?tab=awaiting_agent")
    assert arrival["reference"] in awaiting.text
    # The closed tab holds the issued demonstration case.
    closed = client.get("/queue/intake?tab=closed")
    assert "SYN-APP-007" in closed.text
    # The archived tab holds nothing yet.
    archived = client.get("/queue/intake?tab=archived")
    assert archived.status_code == 200, archived.text


def test_the_bulk_action_refuses_an_empty_selection(
    client: TestClient, environment: Settings
) -> None:
    submit_arrival_as_steward(client)
    choose(client, "persona_agent_operator")
    wake_the_agent(environment)
    csrf = token(client, "/queue/intake")
    response = client.post(
        "/ui/actions/permit.intake.process_selected",
        data={
            "csrf_token": csrf,
            "action_id": "permit.intake.process_selected",
            "next": "/queue/intake",
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["status"] == "denied"
    assert "choose at least one case" in body["message"]
    assert intake_run_count(environment) == 0


def test_the_bulk_action_is_refused_without_the_csrf_token(
    client: TestClient, environment: Settings
) -> None:
    arrival = submit_arrival_as_steward(client)
    choose(client, "persona_agent_operator")
    wake_the_agent(environment)
    response = client.post(
        "/ui/actions/permit.intake.process_selected",
        data={
            "action_id": "permit.intake.process_selected",
            "next": "/queue/intake",
            "selection": f"{arrival['application_id']}:{arrival['version']}",
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 403, response.text
    assert intake_run_count(environment) == 0


def test_the_bulk_action_processes_the_selected_cases(
    client: TestClient, environment: Settings
) -> None:
    arrival = submit_arrival_as_steward(client)
    choose(client, "persona_agent_operator")
    wake_the_agent(environment)
    csrf = token(client, "/queue/intake")
    response = client.post(
        "/ui/actions/permit.intake.process_selected",
        data={
            "csrf_token": csrf,
            "action_id": "permit.intake.process_selected",
            "next": "/queue/intake",
            "selection": f"{arrival['application_id']}:{arrival['version']}",
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"
    assert intake_run_count(environment) == 1


def test_the_bulk_action_is_refused_while_the_agent_sleeps(
    client: TestClient, environment: Settings
) -> None:
    arrival = submit_arrival_as_steward(client)
    choose(client, "persona_agent_operator")
    csrf = token(client, "/queue/intake")
    response = client.post(
        "/ui/actions/permit.intake.process_selected",
        data={
            "csrf_token": csrf,
            "action_id": "permit.intake.process_selected",
            "next": "/queue/intake",
            "selection": f"{arrival['application_id']}:{arrival['version']}",
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert "asleep" in response.json()["message"]
    assert intake_run_count(environment) == 0


def test_the_bulk_action_is_refused_for_a_persona_without_the_grant(
    client: TestClient, environment: Settings
) -> None:
    choose(client, "persona_city_administrator")
    wake_the_agent(environment)
    response = client.post(
        "/ui/actions/permit.intake.process_selected",
        data={
            "csrf_token": token(client, "/admin"),
            "action_id": "permit.intake.process_selected",
            "next": "/queue",
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 403, response.text
    assert intake_run_count(environment) == 0


# ------------------------------------------------------ guarded-button reasons

def test_the_disabled_bulk_button_says_why_while_the_agent_sleeps(client: TestClient) -> None:
    choose(client, "persona_agent_operator")
    page = client.get("/queue/intake").text
    flat = page.replace("\n", " ")
    assert re.search(r'data-testid="intake-bulk-submit"\s+disabled aria-describedby="intake-bulk-reason"', flat)
    assert 'id="intake-bulk-reason"' in page
    assert "The intake agent is asleep" in page
    assert "No case is in this view to process." not in page  # rows exist, so that is not the reason
    assert "Your role cannot run the intake agent." not in page


def test_the_workspace_rerun_buttons_say_why_they_are_off(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    arrival = submit_arrival(client)
    page = client.get(f"/permits/{arrival['application_id']}").text
    assert 'id="rerun-locked"' in page
    flat = page.replace("\n", " ")
    assert re.search(r'data-testid="rerun-intake"\s+disabled aria-describedby="rerun-locked"', flat)
    assert "Re-run intake agent: the intake agent is asleep." in page
    assert "Re-run adjudication: your role cannot do this." in page


# --------------------------------------------------- read grant and run grant

def test_the_data_steward_keeps_the_intake_queue_after_the_run_grant_moved(
    client: TestClient,
) -> None:
    """The read grant keeps the queue open to the persona that works it."""
    choose(client, "persona_data_steward")
    response = client.get("/queue/intake")
    assert response.status_code == 200, response.text
    assert 'data-testid="intake-table"' in response.text


def test_the_data_steward_reads_the_queue_but_cannot_process_it(
    client: TestClient,
) -> None:
    """The processing control is locked for a persona that may only read."""
    choose(client, "persona_data_steward")
    page = client.get("/queue/intake").text
    flat = page.replace("\n", " ")
    assert re.search(
        r'data-testid="intake-bulk-submit"\s+disabled aria-describedby="intake-bulk-reason"',
        flat,
    )
    assert "Your role cannot run the intake agent." in page
    # A read only queue offers no selection to process.
    assert 'data-testid="intake-select"' not in page


def test_the_processing_control_is_open_to_the_agent_operator(
    client: TestClient, environment: Settings
) -> None:
    """The persona that may run the intake agent may process the selection."""
    submit_arrival_as_steward(client)
    choose(client, "persona_agent_operator")
    wake_the_agent(environment)
    page = client.get("/queue/intake").text
    assert 'data-testid="intake-select"' in page
    assert "Your role cannot run the intake agent." not in page
    assert "The intake agent is asleep." not in page
