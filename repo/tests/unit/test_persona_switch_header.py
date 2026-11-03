"""The persona menu in the top right of the staff frame.

The demo switcher is a header control now: the chip in the top right names the
persona that acts, and its menu offers the five personas.  The bottom-left
overlay is gone.  The City website header carries the same menu for a signed-in
persona and nothing for a signed-out visitor.
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

#: The public City pages, which carry the menu for a signed-in persona.
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


def chip_of(body: str) -> str:
    """Return the markup of the chip of the persona (the summary)."""
    match = re.search(r'<summary class="account-trigger".*?</summary>', body, re.S)
    assert match is not None, "the page carries no persona chip"
    return match.group(0)


def menu_head_of(body: str) -> str:
    """Return the markup of the head of the menu, above its items."""
    match = re.search(
        r'<div class="account-panel">(.*?)<p class="account-switch-label">', body, re.S
    )
    assert match is not None, "the page carries no persona menu"
    return match.group(1)


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


def test_the_chip_is_one_line_and_the_menu_opens_with_the_name(
    client: TestClient,
) -> None:
    """The chip holds the role alone; the name of the person opens the menu.

    The chip used to hold two lines, the role and the name of the person, so
    the dot was centred between the two of them.  The chip is one line now:
    the name of the person is the first line of the menu the chip opens, and
    the tooltip of the chip.
    """
    choose(client, "persona_applicant")
    # The staff frame: the chip carries the role, and nothing else.
    body = client.get("/permits/app_d05").text
    chip = chip_of(body)
    assert 'data-testid="account-sub"' not in chip
    # The chip is one line: the role, and nothing else.
    assert re.sub(r"<[^>]+>", " ", chip).split() == ["Applicant"]
    # The name of the person is the tooltip of the chip...
    assert 'title="Demo Applicant"' in chip
    # ... and the first line of the menu, above its items.
    head = menu_head_of(body)
    assert 'data-testid="account-sub">Demo Applicant<' in head
    assert head.index("Demo Applicant") < head.index("Signed in as")
    # The City frame carries the same chip under its own test id.
    body = client.get("/city/").text
    chip = chip_of(body)
    assert re.sub(r"<[^>]+>", " ", chip).split() == ["Applicant"]
    assert 'title="Demo Applicant"' in chip
    head = menu_head_of(body)
    assert 'data-testid="applicant-name">Demo Applicant<' in head
    assert head.index("Demo Applicant") < head.index("Signed in as")


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
    # The menu posts the home of the persona that was picked, the same
    # target the landing cards use, so the switch is not redirected.
    assert target.group(1) == home, markup
    response = client.post(
        "/ui/actor",
        data={"actor_id": actor_id, "next": target.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:200]
    assert response.headers["location"] == home, response.headers["location"]
    assert client.get("/api/session").json()["actor_id"] == actor_id


# ------------------------------------------------------- the old overlay


@pytest.mark.parametrize("path", STAFF_PAGES)
def test_the_bottom_left_overlay_is_gone(client: TestClient, path: str) -> None:
    """The staff frame carries no floating switcher any more."""
    body = client.get(path).text
    assert 'class="demo-switch' not in body, path
    assert "demo-corner-bottom-left" not in body, path
    assert "Open the City website home" not in body, path


def city_header_of(body: str) -> str:
    """Return the markup of the City header."""
    match = re.search(r'<header class="city-header">(.*?)</header>', body, re.S)
    assert match is not None, "the page carries no City header"
    return match.group(0)


@pytest.mark.parametrize("path", CITY_PAGES)
def test_the_city_header_carries_the_persona_menu_for_the_applicant(
    client: TestClient, path: str
) -> None:
    """A signed-in persona sees the Demo controls menu in the City header."""
    choose(client, "persona_applicant")
    body = client.get(path).text
    header = city_header_of(body)
    assert 'data-testid="persona-trigger"' in header, path
    assert 'data-testid="demo-switch"' in header, path
    assert "Demo controls" in header, path
    menu = menu_of(header)
    assert len(re.findall(r'data-demo-persona="', menu)) == 5, path
    current = re.search(r'data-demo-persona="([^"]+)"[^>]*aria-current="true"', menu)
    assert current is not None and current.group(1) == "persona_applicant", path
    # Sign out lives inside the menu, and the old floating overlay stays gone.
    assert header.count('data-testid="sign-out"') == 1, path
    assert header.index('data-testid="sign-out"') > header.index('data-testid="demo-switch"'), path
    assert 'class="demo-switch' not in body, path


@pytest.mark.parametrize(("actor_id", "label", "home"), PERSONAS)
def test_every_city_menu_item_switches_to_that_personas_home(
    client: TestClient, actor_id: str, label: str, home: str
) -> None:
    """Each item of the City menu posts the persona and lands on its home."""
    choose(client, "persona_applicant")
    menu = menu_of(city_header_of(client.get("/city/").text))
    form = re.search(
        rf'<form method="post" action="/ui/actor">(?:(?!</form>).)*?'
        rf'data-demo-persona="{actor_id}"(?:(?!</form>).)*?</form>',
        menu,
        re.S,
    )
    assert form is not None, actor_id
    target = re.search(r'name="next" value="([^"]+)"', form.group(0))
    assert target is not None
    assert target.group(1) == home
    response = client.post(
        "/ui/actor",
        data={"actor_id": actor_id, "next": target.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:200]
    assert response.headers["location"] == home, response.headers["location"]
    assert client.get("/api/session").json()["actor_id"] == actor_id


def test_the_city_menu_and_the_staff_menu_share_one_markup() -> None:
    """The menu is one shared template, not a copy in each frame."""
    templates = ROOT / "src" / "acme_city" / "templates"
    shared = (templates / "_persona_menu.html").read_text(encoding="utf-8")
    assert 'data-testid="demo-switch"' in shared
    for name in ("base.html", "city/layout.html"):
        text = (templates / name).read_text(encoding="utf-8")
        assert "persona_menu(" in text, name
        assert 'data-testid="demo-switch"' not in text, name
        assert "data-demo-persona" not in text, name


@pytest.mark.parametrize("path", CITY_PAGES)
def test_a_signed_out_city_visitor_sees_no_menu(settings: Settings, path: str) -> None:
    """Without a session the City header offers no persona menu."""
    with TestClient(create_app(settings)) as visitor:
        body = visitor.get(path, follow_redirects=True).text
    assert 'data-testid="persona-trigger"' not in body, path
    assert "data-demo-persona" not in body, path
    assert 'data-testid="demo-switch"' not in body, path


# -------------------------------------------------------------- the copy


def test_no_copy_says_where_the_control_used_to_sit() -> None:
    """The words of the frames do not name the old corner."""
    for name in ("base.html", "city/layout.html"):
        text = (ROOT / "src" / "acme_city" / "templates" / name).read_text(encoding="utf-8")
        text = re.sub(r"\{#.*?#\}", " ", text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        assert "bottom left" not in text.lower(), name
        assert "bottom-left" not in text.lower(), name
