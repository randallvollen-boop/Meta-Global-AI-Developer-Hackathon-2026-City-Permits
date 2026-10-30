"""The early resolution board is a Data Steward screen, and it changes nothing.

The board groups the cases that wait for a person by the finding that puts
them there.  The membership, the grouping and the order are the recorded
facts: the board shows them and it decides nothing.  Only the Data Steward
may open it.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02, PER-03, PER-04

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
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

#: The personas that may not open the board.
OUTSIDE = (
    "persona_applicant",
    "persona_permit_reviewer",
    "persona_city_administrator",
)


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'early-resolution.db'}",
            "ACME_SECRET_KEY": "early-resolution-regression-secret-value",
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
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


@pytest.fixture()
def waiting_case(environment: Settings) -> str:
    """Put one demonstration case into early resolution with a recorded finding.

    The demonstration corpus holds no case that waits for a person, so the
    board would show nothing.  The case below is fictional and belongs to the
    demonstration.
    """
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == "SYN-APP-007"
                )
            ).scalar_one()
            application.status = "needs_information"
            session.add(
                permit.ApplicationFinding(
                    id="finding_early_resolution_regression",
                    correlation_id="correlation_early_resolution_regression",
                    application_id=application.id,
                    finding_type="missing_document",
                    message="The site plan carries no signature.",
                    rule="A site plan needs a signature.",
                    applicant_must="Send a signed site plan.",
                    severity="block",
                    state="current",
                    revision_number=application.revision,
                )
            )
            return application.source_application_number
    finally:
        factory.dispose()


def waiting_references(environment: Settings) -> list[str]:
    """Return the cases that wait for a person, in the order of the board."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(permit.Application.source_application_number).where(
                    permit.Application.status == "needs_information",
                    permit.Application.synthetic.is_(False),
                )
            ).scalars().all()
            return sorted(rows)
    finally:
        factory.dispose()


@pytest.mark.parametrize("actor_id", OUTSIDE)
def test_the_board_is_refused_outside_the_data_steward(
    client: TestClient, actor_id: str
) -> None:
    """The early resolution board belongs to the Data Steward."""
    choose(client, actor_id)
    response = client.get("/queue/early-resolution")
    assert response.status_code == 403, (actor_id, response.status_code)


def test_the_data_steward_opens_the_board(client: TestClient) -> None:
    """The Data Steward opens the board and it answers."""
    choose(client, "persona_data_steward")
    response = client.get("/queue/early-resolution")
    assert response.status_code == 200, response.text
    assert 'data-testid="early-resolution-kpis"' in response.text


def test_the_board_holds_the_cases_that_wait_for_a_person(
    client: TestClient, environment: Settings, waiting_case: str
) -> None:
    """The membership of the board is the cases in needs information."""
    choose(client, "persona_data_steward")
    page = client.get("/queue/early-resolution").text
    shown = set(re.findall(r'class="ref"><a [^>]*>([^<]+)</a>', page))
    assert shown == set(waiting_references(environment))


def test_the_board_shows_no_case_that_does_not_wait(
    client: TestClient, environment: Settings, waiting_case: str
) -> None:
    """A case that is not waiting for a person is not on the board."""
    choose(client, "persona_data_steward")
    page = client.get("/queue/early-resolution").text
    waiting = waiting_references(environment)
    for reference in ("SYN-APP-001", "SYN-APP-002"):
        if reference in waiting:
            continue
        assert reference not in page


def test_every_case_of_the_board_names_its_next_step(
    client: TestClient, waiting_case: str
) -> None:
    """Every case row says what happens next."""
    choose(client, "persona_data_steward")
    page = client.get("/queue/early-resolution").text
    steps = page.split('data-testid="early-resolution-next-step"')[1:]
    assert steps
    for part in steps:
        text = part.split(">", 1)[1].split("<", 1)[0]
        assert text.strip()


def test_the_group_of_a_case_is_its_primary_finding(client: TestClient) -> None:
    """A case sits under the group of its own primary finding."""
    choose(client, "persona_data_steward")
    page = client.get("/queue/early-resolution").text
    groups = page.split('data-testid="early-resolution-group"')[1:]
    for group in groups:
        finding_type = group.split('data-finding-type="', 1)[1].split('"', 1)[0]
        for part in group.split('data-testid="early-resolution-case"')[1:]:
            assert finding_type in part
