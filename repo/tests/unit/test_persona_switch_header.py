"""The persona menu in the top right of the staff frame.

The demo switcher is a header control now: the chip in the top right names the
persona that acts, and its menu offers the five personas.  The bottom-left
overlay is gone, and the public City website carries no switcher at all.
"""
# REQUIRES: UX-01, PER-04

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402

#: The five selectable personas, and the home each one lands on.
PERSONAS = (
    ("persona_applicant", "Applicant", "/city/"),
    ("persona_agent_operator", "Agent Operator", "/agents"),
    ("persona_data_steward", "Data Steward", "/steward"),
    ("persona_permit_reviewer", "Permit Reviewer", "/queue"),
    ("persona_city_administrator", "City Administrator", "/overview"),
)

#: The staff pages the Data Steward can open.
STAFF_PAGES = ("/steward", "/masters", "/source-records", "/activity", "/queue")

#: The public City pages, which carry no switcher.
CITY_PAGES = ("/city/", "/city/community", "/city/permits", "/apply")


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    """A demonstration database with the personas seeded."""
    return build_environment(
        tmp_path_factory.mktemp("persona-header"), synthetic=False, name="persona-header.db"
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    """A client that acts as the Data Steward."""
    with TestClient(create_app(settings)) as test_client:
        choose(test_client, "persona_data_steward")
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def header_of(body: str) -> str:
    """Return the markup of the top bar of a staff page."""
    match = re.search(r'<header class="top app-header">(.*?)</header>', body, re.S)
    assert match is not None, "the page carries no top bar"
    return match.group(0)


def menu_of(body: str) -> str:
    """Return the markup of the persona menu."""
    match = re.search(r'<ul class="account-personas"[^>]*>(.*?)</ul>', body, re.S)
    assert match is not None, "the page carries no persona menu"
    return match.group(0)


# ------------------------------------------------------------- the chip


def test_the_chip_in_the_top_right_names_the_persona_that_acts(
    client: TestClient,
) -> None:
    """The header names the acting persona and opens the menu."""
    body = client.get("/queue").text
    header = header_of(body)
    assert 'data-testid="persona-trigger"' in header
    assert 'data-testid="acting-persona"' in header
    assert "Data Steward" in header
    # The menu is inside the header, not in a floating overlay.
    assert 'data-testid="demo-switch"' in header


def test_the_menu_offers_the_five_personas_and_marks_the_current_one(
    client: TestClient,
) -> None:
    """Every persona is offered and the acting one is marked."""
    menu = menu_of(client.get("/queue").text)
    assert len(re.findall(r'data-demo-persona="', menu)) == 5
    for actor_id, label, _home in PERSONAS:
        assert f'data-demo-persona="{actor_id}"' in menu, actor_id
        assert label in menu, actor_id
    current = re.search(r'data-demo-persona="([^"]+)"[^>]*aria-current="true"', menu)
    assert current is not None, menu
    assert current.group(1) == "persona_data_steward"


@pytest.mark.parametrize(("actor_id", "label", "home"), PERSONAS)
def test_every_persona_item_posts_to_the_persona_selector(
    client: TestClient, actor_id: str, label: str, home: str
) -> None:
    """Every item of the menu is a form that switches the persona."""
    menu = menu_of(client.get("/queue").text)
    form = re.search(
        rf'<form method="post" action="/ui/actor">(?:(?!</form>).)*?'
        rf'data-demo-persona="{actor_id}"(?:(?!</form>).)*?</form>',
        menu,
        re.S,
    )
    assert form is not None, actor_id
    markup = form.group(0)
    assert f'name="actor_id" value="{actor_id}"' in markup
    target = re.search(r'name="next" value="([^"]+)"', markup)
    assert target is not None, markup
    # The choice lands on the home of the persona that was picked.
    response = client.post(
        "/ui/actor",
        data={"actor_id": actor_id, "next": target.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:200]
    assert response.headers["location"].split("?")[0] == home, response.headers["location"]
    assert client.get("/api/session").json()["actor_id"] == actor_id


# ------------------------------------------------------- the old overlay


@pytest.mark.parametrize("path", STAFF_PAGES)
def test_the_bottom_left_overlay_is_gone(client: TestClient, path: str) -> None:
    """The staff frame carries no floating switcher any more."""
    body = client.get(path).text
    assert 'class="demo-switch' not in body, path
    assert "demo-corner-bottom-left" not in body, path
    assert "Open the City website home" not in body, path


@pytest.mark.parametrize("path", CITY_PAGES)
def test_the_public_city_site_carries_no_switcher(client: TestClient, path: str) -> None:
    """The City website and the permit application carry no switcher."""
    choose(client, "persona_applicant")
    body = client.get(path).text
    assert "data-demo-persona" not in body, path
    assert 'class="demo-switch' not in body, path


# -------------------------------------------------------------- the copy


def test_no_copy_says_where_the_control_used_to_sit() -> None:
    """The words of the frames do not name the old corner."""
    for name in ("base.html", "city/layout.html"):
        text = (ROOT / "src" / "acme_city" / "templates" / name).read_text(encoding="utf-8")
        text = re.sub(r"\{#.*?#\}", " ", text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        assert "bottom left" not in text.lower(), name
        assert "bottom-left" not in text.lower(), name
