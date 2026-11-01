"""The step graph of the agents on the screens of the operator.

The graph of the latest run stands under the buttons that start a run, the
run detail shows the steps of its own attempt, and the fragment route
answers the graph of one attempt to a persona that may read it.
"""
# REQUIRES: UX-01, UX-02

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
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

#: The states of the cards of a rendered graph, read from the markup.
STATES = re.compile(r'data-node-id="([^"]+)"[^>]*data-state="([^"]+)"', re.S)


def _states(html: str) -> dict[str, str]:
    """Return the state of every card of a rendered graph."""
    return dict(STATES.findall(html))


@pytest.fixture()
def environment(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'agent-progress.db'}",
            "ACME_SECRET_KEY": "agent-progress-test-secret",
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
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as client:
        yield client, settings


def _choose(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for one persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def _act(client: TestClient, action_id: str, fields: dict[str, str]) -> dict:
    """Send one interface action, the way a click sends it."""
    page = client.get("/agent/intake").text
    token = re.search(r'name="csrf_token" value="([0-9a-f]+)"', page)
    assert token is not None
    data = {
        "csrf_token": token.group(1),
        "action_id": action_id,
        "next": "/agent/intake",
        **fields,
    }
    response = client.post(
        f"/ui/actions/{action_id}",
        data=data,
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _run_one_case(client: TestClient) -> str:
    """Let the intake agent work on a case that arrived, and return its id."""
    response = client.post("/api/intake/simulate", json={"scenario": "deck-high"})
    assert response.status_code == 200, response.text
    application_id = response.json()["results"][0]["application_id"]
    assert _act(client, "agent.toggle", {"agent_key": "intake", "mode": "awake"})[
        "status"
    ] == "accepted"
    assert _act(client, "agent.run.intake", {"application_id": application_id})[
        "status"
    ] == "accepted"
    return application_id


def _latest_run(settings: Settings, agent_key: str = "intake") -> tuple[str, str]:
    """Return the identifier and the outcome of the latest run of an agent."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            run = session.execute(
                select(agent_models.AgentRun)
                .where(agent_models.AgentRun.agent_key == agent_key)
                .order_by(
                    agent_models.AgentRun.started_at.desc(),
                    agent_models.AgentRun.id.desc(),
                )
            ).scalars().first()
            assert run is not None
            return run.id, run.outcome
    finally:
        factory.dispose()


def _recorded(settings: Settings, run_id: str) -> dict[str, str]:
    """Return the state of every step the run recorded."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(agent_models.AgentRunNode).where(
                    agent_models.AgentRunNode.agent_run_id == run_id
                )
            ).scalars().all()
            return {row.node_id: row.status for row in rows}
    finally:
        factory.dispose()


def test_the_agent_screen_shows_the_graph_of_the_latest_run(environment) -> None:
    """The graph stands under the Process buttons, with the recorded states."""
    client, settings = environment
    _choose(client, "persona_agent_operator")
    _run_one_case(client)
    page = client.get("/agent/intake").text
    run_id, outcome = _latest_run(settings)
    recorded = _recorded(settings, run_id)
    assert len(recorded) == 7
    # Every card of the graph carries the state the run recorded.
    assert _states(page) == recorded
    # The line above the graph names the run and how far it got.
    line = re.search(
        r'data-testid="agent-progress-status"[^>]*>(.*?)</p>', page, re.S
    )
    assert line is not None
    assert line.group(1).strip().startswith("Latest run: ")
    assert "7 of 7 steps" in line.group(1)
    assert outcome.replace("_", " ").capitalize() in line.group(1)
    # The graph stands under the button that starts a run.
    assert page.index('data-testid="agent-run-all"') < page.index(
        'data-testid="agent-progress"'
    )


def test_the_progress_block_is_not_polled_every_five_seconds(environment) -> None:
    """The five second poll would replace the block, so it does not carry it."""
    client, _settings = environment
    _choose(client, "persona_agent_operator")
    page = client.get("/agent/intake").text
    block = re.search(
        r'<section class="agent-progress".*?</section>', page, re.S
    )
    assert block is not None
    assert "data-status-refresh" not in block.group(0)
    assert 'data-run-progress' in block.group(0)
    assert 'aria-live="polite"' in block.group(0)


def test_the_run_detail_shows_the_steps_of_its_own_attempt(environment) -> None:
    """The attempt shows its own graph, with the note of every step."""
    client, settings = environment
    _choose(client, "persona_agent_operator")
    _run_one_case(client)
    run_id, _outcome = _latest_run(settings)
    detail = client.get(f"/agents/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    assert "Processing steps" in detail.text
    assert _states(detail.text) == _recorded(settings, run_id)
    # The Router line of the attempt is on the card of the Router step.
    router = re.search(
        r'data-node-id="router".*?</div>\s*</div>', detail.text, re.S
    )
    assert router is not None
    assert "Ready for review" in router.group(0)


def test_the_case_page_shows_the_graph_of_the_latest_run(environment) -> None:
    """The case of an agent shows the steps the agent took on it."""
    client, settings = environment
    _choose(client, "persona_agent_operator")
    application_id = _run_one_case(client)
    page = client.get(f"/agents/cases/{application_id}")
    assert page.status_code == 200, page.text
    run_id, _outcome = _latest_run(settings)
    assert _states(page.text) == _recorded(settings, run_id)


def test_the_fragment_route_answers_the_graph_of_a_run(environment) -> None:
    """The fragment holds the graph of the run and nothing else."""
    client, settings = environment
    _choose(client, "persona_agent_operator")
    _run_one_case(client)
    run_id, _outcome = _latest_run(settings)
    response = client.get(f"/agents/runs/{run_id}/dag")
    assert response.status_code == 200, response.text
    assert _states(response.text) == _recorded(settings, run_id)
    # The fragment is the graph alone: no state of the agent and no figure.
    assert "Latest run" not in response.text
    assert "kpi" not in response.text


def test_the_fragment_route_is_refused_to_a_persona_that_may_not_read_it(
    environment,
) -> None:
    """An applicant is refused the graph of an attempt."""
    client, settings = environment
    _choose(client, "persona_agent_operator")
    _run_one_case(client)
    run_id, _outcome = _latest_run(settings)
    _choose(client, "persona_applicant")
    response = client.get(f"/agents/runs/{run_id}/dag")
    assert response.status_code == 403, response.text
    assert "data-testid=\"agent-dag-node\"" not in response.text


def test_the_fragment_route_says_when_a_run_does_not_exist(environment) -> None:
    """An unknown attempt answers that it is not available."""
    client, _settings = environment
    _choose(client, "persona_agent_operator")
    response = client.get("/agents/runs/run_that_never_happened/dag")
    assert response.status_code == 404, response.text
