"""Help assertions of the operator lane (the shared test_help_docs.py is frozen)."""
# REQUIRES: UX-01

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.help_docs import content
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

#: The labels the help quotes for the Agent Operator.
OPERATOR_LABELS = ("Agents", "Intake agent", "Adjudication agent", "Agent runs")


@pytest.fixture()
def operator_client(tmp_path: Path):
    """Return a client that acts as the Agent Operator."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'help-operator.db'}",
            "ACME_SECRET_KEY": "help-operator-test-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(DemoEnvironment(
                id="demo_environment_local",
                environment_id=ENVIRONMENT_ID,
                fictional_demo=True,
                fixture_version=bundle.fixture_version,
                label="local fictional demonstration",
            ))
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    finally:
        factory.dispose()
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as client:
        assert client.post(
            "/api/session/select", json={"actor_id": "persona_agent_operator"}
        ).status_code == 200
        yield client


def test_operator_guidance_names_only_the_operator_screens() -> None:
    """The shared help introduction explains the limited operator workspace."""
    intro = content.howto_intro()
    assert "Agent Operator" in intro
    for label in OPERATOR_LABELS:
        assert f'"{label}"' in intro
    assert "permit decisions" in intro


def test_every_label_the_help_quotes_is_on_the_operator_screen(
    operator_client: TestClient,
) -> None:
    """The help names the labels of the navigation, so a reader finds them.

    The help quotes the labels of the screens.  A label that the navigation
    does not show is a label no operator can follow, so the quoted labels are
    checked against the page the help points at.
    """
    page = operator_client.get("/agents")
    assert page.status_code == 200, page.text
    for label in OPERATOR_LABELS:
        assert label in page.text, label
    # The label of the navigation is the one the help quotes.
    assert "Agent runs" in page.text
    assert "Run history" not in content.howto_intro()
