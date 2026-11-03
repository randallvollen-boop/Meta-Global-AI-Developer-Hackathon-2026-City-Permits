"""The breadcrumb of a page is one trail, and it starts at the home of the persona.

A page shows one breadcrumb.  The help pages show the trail of the frame:
Home, Help and documentation and the page itself.  The Home crumb points at
the home of the visitor: the City website for the public and the Applicant,
the own home of a staff persona.  A page that carries its own crumb in its
content (the detail pages with their way back to the list) shows that one
only.
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
def client(tmp_path: Path) -> TestClient:
    """Return a client on a fresh demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'breadcrumbs.db'}",
            "ACME_SECRET_KEY": "breadcrumb-test-secret-value",
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
        yield test_client


def sign_in(client: TestClient, actor_id: str) -> None:
    """Sign the visitor in as one persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def breadcrumbs(page: str) -> list[str]:
    """Return every element of the page that is a breadcrumb.

    A breadcrumb is the trail of the frame (an element that names itself a
    breadcrumb) or a crumb a page carries in its content.
    """
    tags = re.findall(r"<[a-z]+[^>]*>", page)
    return [
        tag
        for tag in tags
        if 'aria-label="Breadcrumb"' in tag or re.search(r'class="[^"]*\bcrumb', tag)
    ]


def trail(page: str) -> list[tuple[str, str]]:
    """Return the items of the trail: the label of every crumb and its link.

    The last item is the page itself, so it has no link.
    """
    block = re.search(r"<nav[^>]*aria-label=\"Breadcrumb\"[^>]*>(.*?)</nav>", page, re.S)
    assert block is not None, "the page has no breadcrumb"
    items = []
    for item in re.findall(r"<li>(.*?)</li>", block.group(1), re.S):
        link = re.search(r"href=\"([^\"]*)\"", item)
        items.append((re.sub(r"<[^>]+>", "", item).strip(), link.group(1) if link else ""))
    return items


def test_a_help_page_shows_one_trail_for_the_applicant(client: TestClient) -> None:
    """The Applicant reads the trail of the City website."""
    sign_in(client, "persona_applicant")
    page = client.get("/help/tutorial").text
    assert len(breadcrumbs(page)) == 1, breadcrumbs(page)
    assert trail(page) == [
        ("Home", "/city/"),
        ("Help and documentation", "/help"),
        ("Tutorial", ""),
    ]


def test_a_help_page_shows_one_trail_for_a_staff_persona(client: TestClient) -> None:
    """A staff persona reads the trail of the staff application."""
    sign_in(client, "persona_permit_reviewer")
    page = client.get("/help/tutorial").text
    assert len(breadcrumbs(page)) == 1, breadcrumbs(page)
    assert trail(page) == [
        ("Home", "/queue"),
        ("Help and documentation", "/help"),
        ("Tutorial", ""),
    ]


@pytest.mark.parametrize(
    ("actor_id", "home"),
    [
        ("persona_applicant", "/city/"),
        ("persona_data_steward", "/steward"),
        ("persona_permit_reviewer", "/queue"),
        ("persona_city_administrator", "/overview"),
        ("persona_agent_operator", "/agents"),
    ],
)
def test_the_home_crumb_points_at_the_home_of_the_persona(
    client: TestClient, actor_id: str, home: str
) -> None:
    """Home is the City website for the Applicant and the own home of a staff persona."""
    sign_in(client, actor_id)
    page = client.get("/help/tutorial").text
    assert len(breadcrumbs(page)) == 1, breadcrumbs(page)
    assert trail(page)[0] == ("Home", home)


@pytest.mark.parametrize(
    ("path", "page"),
    [
        ("/help/tutorial", "Tutorial"),
        ("/help/how-to", "How-to guides"),
        ("/help/how-to/apply-for-a-fence-or-deck-permit", "Apply for a fence or deck permit"),
        ("/help/glossary", "Glossary"),
        ("/help/technical", "Technical documentation"),
        ("/help/technical/architecture", "Solution architecture"),
    ],
)
def test_every_help_page_shows_the_same_three_part_trail(
    client: TestClient, path: str, page: str
) -> None:
    """Every page of the help section carries the trail of the section."""
    sign_in(client, "persona_applicant")
    body = client.get(path).text
    assert len(breadcrumbs(body)) == 1, breadcrumbs(body)
    assert trail(body) == [
        ("Home", "/city/"),
        ("Help and documentation", "/help"),
        (page, ""),
    ]


def test_the_help_hub_is_the_help_section_itself(client: TestClient) -> None:
    """The hub is the section, so the trail names it once."""
    sign_in(client, "persona_applicant")
    body = client.get("/help").text
    assert len(breadcrumbs(body)) == 1, breadcrumbs(body)
    assert trail(body) == [("Home", "/city/"), ("Help and documentation", "")]


@pytest.mark.parametrize(
    "path",
    [
        "/steward/batch",
        "/applicants/party_cedarline",
        "/masters/party_cedarline",
    ],
)
def test_a_detail_page_shows_its_own_crumb_only(client: TestClient, path: str) -> None:
    """A page with a crumb in its content shows no second trail in the frame."""
    sign_in(client, "persona_data_steward")
    body = client.get(path).text
    assert len(breadcrumbs(body)) == 1, breadcrumbs(body)
    assert '<p class="crumb">' in body


def test_a_staff_list_page_shows_one_trail(client: TestClient) -> None:
    """A list page of the staff application shows the trail of the frame."""
    sign_in(client, "persona_data_steward")
    body = client.get("/steward").text
    assert len(breadcrumbs(body)) == 1, breadcrumbs(body)
