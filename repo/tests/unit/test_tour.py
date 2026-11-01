"""The guided tour: the steps, the screens and the grants.

The tour walks one permit from the application to the public record.  It
follows the written walkthrough step by step, switches persona through the
ordinary persona switch, opens the real screen and points at the real
control.  It changes no record.

Every step names the persona that acts, the grant that persona needs, the
screen and the control the tour points at.  A step whose persona does not
hold the grant, or whose control is not on the screen, fails here.
"""
# REQUIRES: UX-04, PER-04

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import choose, client, settings  # noqa: E402,F401

from acme_city.auth.permissions import PermissionResolver  # noqa: E402
from acme_city.persistence.session import SessionFactory  # noqa: E402
from acme_city.ui.guide_routes import tour_steps  # noqa: E402
from acme_city.ui.guide_views import WALKTHROUGH  # noqa: E402

CONFIG = Path(__file__).resolve().parents[2] / "config" / "tour_steps.json"

#: The tour points at one control of a screen with an attribute selector.
TARGET = re.compile(r'^\[data-(?P<attribute>[a-z-]+)="(?P<value>[^"]+)"\]$')

#: The personas the tour may act as, in the order of the story.
STORY_ORDER = (
    "Applicant",
    "Agent Operator",
    "Data Steward",
    "Permit Reviewer",
    "City Administrator",
)


@pytest.fixture()
def steps() -> list[dict[str, str]]:
    """The steps of the tour, read from the configuration."""
    return list(json.loads(CONFIG.read_text(encoding="utf-8"))["steps"])


@pytest.fixture()
def session(settings) -> Session:  # noqa: F811
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as open_session:
            yield open_session
    finally:
        factory.dispose()


def needle(selector: str) -> str:
    """Return the HTML that proves the control of a step is on its screen."""
    match = TARGET.match(selector)
    assert match is not None, f"the tour points at {selector!r}, which is not an attribute selector"
    return f'{match.group("attribute")}="{match.group("value")}"'


def test_every_step_names_a_persona_a_screen_a_control_and_a_caption(
    steps: list[dict[str, str]],
) -> None:
    assert steps, "the tour has no steps"
    for step in steps:
        for field in ("id", "title", "path", "target", "caption"):
            assert str(step.get(field, "")).strip(), (step.get("id"), field)
        assert str(step.get("path", "")).startswith("/"), step.get("id")
        assert len(str(step.get("caption", ""))) < 240, step.get("id")


def test_the_tour_follows_the_written_walkthrough(steps: list[dict[str, str]]) -> None:
    """Each step of the tour is the step of the walkthrough it names."""
    seen = []
    for step in steps:
        number = int(step["walkthrough_step"])
        assert 1 <= number <= len(WALKTHROUGH), step["id"]
        written = WALKTHROUGH[number - 1]
        assert step["title"] == written.title, step["id"]
        assert step["persona"] == written.persona, step["id"]
        assert step["path"] == written.path, step["id"]
        seen.append(number)
    assert seen == sorted(seen), "the tour does not follow the order of the story"
    assert seen[0] == 3, "the tour starts at the application"


def test_the_tour_acts_as_the_personas_of_the_story_in_order(
    steps: list[dict[str, str]],
) -> None:
    personas = [step["persona"] for step in steps if step["persona"]]
    assert personas, "the tour acts as nobody"
    ranks = [STORY_ORDER.index(persona) for persona in personas]
    assert ranks == sorted(ranks), personas
    assert set(personas) == set(STORY_ORDER), personas


def test_every_step_holds_the_grant_its_persona_needs(
    steps: list[dict[str, str]], session: Session
) -> None:
    """A step whose persona lacks the grant fails the test."""
    for step in steps:
        if not step["persona"]:
            assert not step["permission"], step["id"]
            continue
        assert step["permission"], step["id"]
        grants = PermissionResolver(session).grants_for(step["actor_id"])
        held = {grant.action for grant in grants}
        assert step["permission"] in held, (
            f"{step['id']}: {step['persona']} does not hold {step['permission']}"
        )


def test_every_step_points_at_a_control_of_its_screen(
    steps: list[dict[str, str]], client: TestClient
) -> None:
    """The control of every step is really on the screen the step opens."""
    for step in steps:
        if step["actor_id"]:
            choose(client, step["actor_id"])
        response = client.get(step["path"])
        assert response.status_code == 200, (step["id"], response.status_code)
        assert needle(step["target"]) in response.text, (
            step["id"],
            step["target"],
            step["path"],
        )


def test_the_tour_changes_no_record(steps: list[dict[str, str]]) -> None:
    """No step names an action: the tour only opens screens and points."""
    for step in steps:
        assert "/ui/actions/" not in step["path"], step["id"]
        assert "command_key" not in step.get("caption", ""), step["id"]


def test_the_route_serves_the_steps_to_the_browser(client: TestClient) -> None:
    response = client.get("/tour/steps")
    assert response.status_code == 200, response.text[:200]
    payload = response.json()
    assert payload["title"] == "Take the tour"
    assert len(payload["steps"]) == len(tour_steps()["steps"])
    for step in payload["steps"]:
        assert step["path"].startswith("/")
        assert step["target"]


def test_the_overlay_loads_the_script_and_the_stylesheet() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "acme_city"
    template = (root / "templates" / "components" / "tour_overlay.html").read_text(
        encoding="utf-8"
    )
    assert '/ui/static/tour.js' in template
    assert '/ui/static/tour.css' in template
    assert (root / "static" / "tour.js").is_file()
    assert (root / "static" / "tour.css").is_file()


def test_the_script_never_writes_a_record() -> None:
    """The engine only reads the steps and switches persona."""
    root = Path(__file__).resolve().parents[2] / "src" / "acme_city"
    script = (root / "static" / "tour.js").read_text(encoding="utf-8")
    assert 'method: "POST"' in script
    assert "/ui/actor" in script
    assert "/ui/actions/" not in script
    # The only request the engine makes besides the persona switch reads the
    # steps of the tour.
    assert script.count("fetch(") == 2
