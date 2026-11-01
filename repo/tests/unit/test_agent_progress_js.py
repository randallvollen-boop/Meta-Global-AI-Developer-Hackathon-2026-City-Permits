"""The replay of a recorded agent run: the hooks of the screen and the script.

The engine works a case in one request, so the steps of a run are complete
when the screen is read again.  The script replays them on the graph of the
screen; the line above the graph says that the steps are replayed, and it
never says that the run is live.
"""
# REQUIRES: UX-01

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'agent-progress-js.db'}",
            "ACME_SECRET_KEY": "agent-progress-js-test-secret",
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
    with TestClient(app) as test_client:
        assert test_client.post(
            "/api/session/select", json={"actor_id": "persona_agent_operator"}
        ).status_code == 200
        yield test_client


def _block(page: str) -> str:
    """Return the progress block of a rendered screen."""
    block = re.search(r'<section class="agent-progress".*?</section>', page, re.S)
    assert block is not None
    return block.group(0)


def test_the_screen_carries_the_hooks_of_the_replay(client: TestClient) -> None:
    """The screen loads the script and marks the block the script reads."""
    page = client.get("/agent/intake").text
    assert 'src="/ui/static/agent-progress.js"' in page
    block = _block(page)
    assert "data-run-progress" in block
    # The line that names the run is the only part that speaks.
    assert block.count('aria-live="polite"') == 1
    assert 'data-testid="agent-progress-status"' in block
    assert 'data-final-status="Latest run: ' in block
    # The cards carry the state the script moves them through.
    assert 'data-testid="agent-dag-node"' in block
    assert 'data-state="idle"' in block


def test_the_script_says_that_it_replays_and_asks_for_less_motion(
    client: TestClient,
) -> None:
    """The script is served, and it never claims that the run is live."""
    response = client.get("/ui/static/agent-progress.js")
    assert response.status_code == 200, response.text
    script = response.text
    # The line above the graph tells the truth while the steps are replayed.
    assert "Replaying recorded steps" in script
    # A reader who asked for less motion gets the recorded states at once.
    assert "prefers-reduced-motion" in script
    # A screen in a background tab waits for the operator.
    assert "document.hidden" in script


def test_the_feedback_of_an_action_sits_behind_the_disclosure(
    client: TestClient,
) -> None:
    """The script of the page builds the detail list the way the frame does."""
    script = client.get("/ui/static/app.js")
    assert script.status_code == 200, script.text
    assert 'details.className = "feedback-more"' in script.text
    assert 'summary.textContent = "More details"' in script.text
    assert "details.appendChild(list);" in script.text
