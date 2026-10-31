"""The demo controls: the five personas, one line of copy and no dead ends.

The switcher is a demonstration control, not part of the service.  It names
the five personas, it says who is acting now, and it sends every choice to the
persona selector.  The help pages point at the list of personas without naming
where the control sits, so the copy stays true wherever the control lives.
"""
# REQUIRES: UX-01, PER-04

from __future__ import annotations

import json
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

#: The files that carry the words the reader sees.
COPY_FILES = (
    ROOT / "config" / "help_content.json",
    ROOT / "src" / "acme_city" / "templates" / "help.html",
    ROOT / "src" / "acme_city" / "templates" / "_demo_switch.html",
)


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    """A demonstration database with the personas seeded."""
    return build_environment(
        tmp_path_factory.mktemp("demo-switch"), synthetic=False, name="demo-switch.db"
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    """A client that acts as the Data Steward."""
    with TestClient(create_app(settings)) as test_client:
        response = test_client.post(
            "/api/session/select", json={"actor_id": "persona_data_steward"}
        )
        assert response.status_code == 200, response.text
        yield test_client


def switcher_of(body: str) -> str:
    """Return the markup of the demo switch on a rendered page."""
    match = re.search(
        r'<details class="demo-switch[^"]*"[^>]*data-testid="demo-switch"[^>]*>(.*?)</details>',
        body,
        re.S,
    )
    assert match is not None, "the page carries no demo switch"
    return match.group(0)


def forms_of(markup: str) -> dict[str, tuple[str, str]]:
    """Return the actor id, destination and label of every persona button."""
    found: dict[str, tuple[str, str]] = {}
    for form in re.findall(r"<form[^>]*>(.*?)</form>", markup, re.S):
        actor = re.search(r'name="actor_id" value="([^"]+)"', form)
        target = re.search(r'name="next" value="([^"]+)"', form)
        button = re.search(r'data-demo-persona="([^"]+)"[^>]*>(.*?)</button>', form, re.S)
        if actor and target and button:
            label = re.sub(r"<[^>]+>", " ", button.group(2))
            found[actor.group(1)] = (target.group(1), " ".join(label.split()))
    return found


# ------------------------------------------------------------ the switcher


def test_the_switcher_names_the_five_personas_and_the_current_one(
    client: TestClient,
) -> None:
    """The panel lists every persona and says who is acting now."""
    markup = switcher_of(client.get("/queue").text)
    assert "Now acting as <strong>Data Steward</strong>" in markup
    assert len(re.findall(r'data-demo-persona="', markup)) == 5
    assert 'aria-label="Demo controls: switch user"' in markup
    assert "<span>Demo controls</span>" in markup


def test_the_switcher_carries_no_long_note_and_no_home_link(
    client: TestClient,
) -> None:
    """The demonstration note and the City home link are gone."""
    markup = switcher_of(client.get("/queue").text)
    assert "Demonstration control for switching users" not in markup
    assert "In a real deployment" not in markup
    assert "Open the City website home" not in markup
    assert 'href="/city/"' not in markup


@pytest.mark.parametrize(("actor_id", "label", "home"), PERSONAS)
def test_every_persona_button_switches_the_actor_and_lands_on_its_home(
    client: TestClient, actor_id: str, label: str, home: str
) -> None:
    """Every button posts to the persona selector and lands on that home."""
    forms = forms_of(switcher_of(client.get("/queue").text))
    assert actor_id in forms, (actor_id, sorted(forms))
    target, button_label = forms[actor_id]
    assert label in button_label, (actor_id, button_label)

    response = client.post(
        "/ui/actor",
        data={"actor_id": actor_id, "next": target},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:200]
    location = response.headers["location"]
    assert location.split("?")[0] == home, (actor_id, location)
    landed = client.get(location)
    assert landed.status_code == 200, location
    # The persona is the one that was picked.
    assert client.get("/api/session").json()["actor_id"] == actor_id


# -------------------------------------------------------------- the copy


@pytest.mark.parametrize("path", COPY_FILES, ids=lambda path: path.name)
def test_no_copy_names_where_the_control_sits(path: Path) -> None:
    """The words never tell the reader where the control sits."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        # The markup of a template: only the words the reader sees are copy.
        text = re.sub(r"\{#.*?#\}", " ", text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
    assert "bottom left" not in text.lower(), path.name
    assert "bottom-left" not in text.lower(), path.name


def test_the_help_pages_point_at_the_list_of_personas(client: TestClient) -> None:
    """The how-to page and the tutorial name the list, not a position."""
    how_to = client.get("/help/how-to/apply-for-a-fence-or-deck-permit").text
    who = re.search(r'<p class="help-who"[^>]*>(.*?)</p>', how_to, re.S)
    assert who is not None, how_to[:400]
    text = re.sub(r"<[^>]+>", " ", who.group(1))
    assert "list of personas" in text
    assert "Demo controls" not in text
    assert "bottom left" not in text.lower()
    tutorial = client.get("/help/tutorial").text
    assert "list of personas" in tutorial
    assert "bottom left" not in tutorial.lower()


def test_the_tutorial_names_the_seeded_applicant_email(client: TestClient) -> None:
    """The tutorial uses the generic address of the seeded applicant."""
    content = json.loads((ROOT / "config" / "help_content.json").read_text(encoding="utf-8"))
    steps = content["tutorial"]["sections"][0]["steps"]
    text = " ".join(step["do"] for step in steps)
    assert "demo.applicant@example.invalid" in text
    assert "t.aldous" not in text
