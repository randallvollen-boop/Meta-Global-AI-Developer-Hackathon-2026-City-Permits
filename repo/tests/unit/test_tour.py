"""The guided tour: the paths, the screens and the grants.

The tour walks one path of the walkthrough.  It follows the written steps of
that path, switches persona through the ordinary persona switch, opens the
real screen and points at the real control.  It changes no record, apart from
the one step that offers a fresh copy of the café case.

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
from acme_city.ui.guide_views import DEFAULT_CASE_ID, PATHS, resolve_path  # noqa: E402

CONFIG = Path(__file__).resolve().parents[2] / "config" / "tour_steps.json"

#: The engine of the tour and the stylesheet that goes with it.
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "src" / "acme_city" / "static" / "tour.js"
STYLE = ROOT / "src" / "acme_city" / "static" / "tour.css"

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
def paths() -> dict[str, dict]:
    """The paths of the tour, read from the configuration."""
    return dict(json.loads(CONFIG.read_text(encoding="utf-8"))["paths"])


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


def test_the_configuration_holds_one_path_for_every_path_of_the_walkthrough(
    paths: dict[str, dict],
) -> None:
    """The tour and the written walkthrough offer the same paths, in the same order."""
    assert list(paths) == [path.key for path in PATHS]
    assert set(paths) == {path.key for path in PATHS}


def test_every_path_names_a_title_and_a_length(paths: dict[str, dict]) -> None:
    for key, path in paths.items():
        assert str(path.get("title", "")).strip(), key
        assert int(path.get("minutes", 0)) > 0, key
        assert path.get("steps"), key


def test_every_step_names_a_persona_a_screen_a_control_and_a_caption(
    paths: dict[str, dict],
) -> None:
    for key, path in paths.items():
        for step in path["steps"]:
            for field in ("id", "title", "path", "caption"):
                assert str(step.get(field, "")).strip(), (key, step.get("id"), field)
            assert str(step.get("path", "")).startswith("/"), step.get("id")
            caption = str(step.get("caption", ""))
            assert "We are here because" in caption, (key, step.get("id"))
            assert len(caption) < 240, step.get("id")
            assert "—" not in caption and "–" not in caption and " - " not in caption
            # A story intro names no control. Every other step still points at one.
            # An intro stays under 400 characters, and under 240 with the rest.
            if str(step.get("kind") or "") == "intro":
                assert step.get("target") == "", (key, step.get("id"))
                assert len(caption) < 400, step.get("id")
            else:
                assert str(step.get("target", "")).strip(), (key, step.get("id"), "target")


def test_the_tour_of_every_path_follows_the_written_steps_of_that_path(
    paths: dict[str, dict],
) -> None:
    """Each step of the tour is a step of the walkthrough of the same path."""
    for path in PATHS:
        tour = paths[path.key]
        seen = []
        for step in tour["steps"]:
            # A story intro is not one of the numbered written steps.
            if str(step.get("kind") or "") == "intro":
                assert "walkthrough_step" not in step, (path.key, step["id"])
                assert step.get("target") == "", (path.key, step["id"])
                continue
            # An extra Muse highlight has a real control and no written number.
            if "walkthrough_step" not in step:
                assert step.get("muse") is True, (path.key, step.get("id"))
                assert str(step.get("target") or "").strip(), (path.key, step.get("id"))
                continue
            number = int(step["walkthrough_step"])
            assert 1 <= number <= len(path.steps), (path.key, step["id"])
            written = path.steps[number - 1]
            assert step["title"] == written.title, (path.key, step["id"])
            assert step["persona"] == written.persona, (path.key, step["id"])
            seen.append(number)
        assert seen == list(range(1, len(path.steps) + 1)), (
            f"the tour of {path.key} does not follow the order of the story"
        )


def test_the_tour_of_the_café_path_starts_at_the_first_step(paths: dict[str, dict]) -> None:
    """The café path opens on its story, then the task of the Data Steward."""
    steps = paths["cafe"]["steps"]
    assert steps[0].get("kind") == "intro"
    assert steps[0].get("target") == ""
    numbered = [step for step in steps if "walkthrough_step" in step]
    assert int(numbered[0]["walkthrough_step"]) == 1
    assert numbered[0]["persona"] == "Data Steward"
    assert numbered[0]["id"] == "steward"


def test_the_tour_of_every_path_acts_as_the_personas_of_that_path(
    paths: dict[str, dict],
) -> None:
    """Every path is walked by the personas of the City and by nobody else.

    The path that prepares a visitor names no persona: the video, the life
    cycle and the help hub are open to anyone.
    """
    for key, path in paths.items():
        personas = [step["persona"] for step in path["steps"] if step["persona"]]
        if key == "before":
            assert not personas, key
            continue
        assert personas, key
        for persona in personas:
            assert persona in STORY_ORDER, (key, persona)


def test_the_paths_together_walk_with_every_persona(paths: dict[str, dict]) -> None:
    """The paths of the tour name every persona of the City between them."""
    personas = {
        step["persona"]
        for path in paths.values()
        for step in path["steps"]
        if step["persona"]
    }
    assert personas == set(STORY_ORDER)


def test_every_step_holds_the_grant_its_persona_needs(
    paths: dict[str, dict], session: Session
) -> None:
    """A step whose persona lacks the grant fails the test."""
    for key, path in paths.items():
        for step in path["steps"]:
            if not step["persona"]:
                assert not step["permission"], (key, step["id"])
                continue
            assert step["permission"], (key, step["id"])
            grants = PermissionResolver(session).grants_for(step["actor_id"])
            held = {grant.action for grant in grants}
            assert step["permission"] in held, (
                f"{key}: {step['id']}: {step['persona']} does not hold {step['permission']}"
            )


def test_every_step_points_at_a_control_of_its_screen(
    paths: dict[str, dict], client: TestClient
) -> None:
    """The control of every step is really on the screen the step opens."""
    for key, path in paths.items():
        for step in path["steps"]:
            if step["actor_id"]:
                choose(client, step["actor_id"])
            screen = resolve_path(str(step["path"]), DEFAULT_CASE_ID)
            response = client.get(screen)
            assert response.status_code == 200, (key, step["id"], response.status_code)
            if str(step.get("kind") or "") == "intro":
                assert step.get("target") == "", (key, step["id"])
                continue
            assert needle(step["target"]) in response.text, (
                key,
                step["id"],
                step["target"],
                screen,
            )


def test_the_tour_changes_no_record(paths: dict[str, dict]) -> None:
    """No step names an action: the tour only opens screens and points."""
    for key, path in paths.items():
        for step in path["steps"]:
            assert "/ui/actions/" not in step["path"], (key, step["id"])
            assert "command_key" not in step.get("caption", ""), (key, step["id"])


def test_only_the_first_step_of_the_café_path_offers_a_fresh_copy(
    paths: dict[str, dict],
) -> None:
    """The one write of the tour is offered on the first step of the café path."""
    fresh = [
        (key, step["id"])
        for key, path in paths.items()
        for step in path["steps"]
        if step.get("fresh")
    ]
    assert fresh == [("cafe", "steward")]


def test_the_route_serves_the_steps_of_the_chosen_path(client: TestClient) -> None:
    """Take the tour, with no path named, opens on the fence story."""
    response = client.get("/tour/steps")
    assert response.status_code == 200, response.text[:200]
    payload = response.json()
    assert payload["title"] == "Take the tour"
    assert payload["path"] == "story"
    assert [item["key"] for item in payload["paths"]] == [item.key for item in PATHS]
    steps = payload["steps"]
    assert [(step.get("path_key"), step.get("id")) for step in steps] == [
        ("resident", "intro"),
        ("resident", "ask"),
        ("resident", "apply"),
        ("resident", "check"),
        ("resident", "agent"),
        ("resident", "track"),
        ("cafe", "bridge-cafe"),
        ("cafe", "intro"),
        ("cafe", "steward"),
        ("cafe", "agent"),
        ("cafe", "reviewer"),
        ("cafe", "finance"),
        ("cafe", "issue"),
        ("cafe", "public"),
        ("city", "bridge-city"),
        ("city", "intro"),
        ("city", "audit"),
        ("city", "insight"),
        ("city", "whatif"),
    ]
    first = steps[0]
    assert first["kind"] == "intro"
    assert first["target"] == ""
    assert first["persona"] == "Applicant"
    assert "fence" in first["title"].lower()
    assert "back yard" in first["caption"]
    bridges = [step for step in steps if step.get("kind") == "bridge"]
    assert [step["caption"] for step in bridges] == [
        "The resident's case is in. Now the City clears a café that has been waiting for weeks.",
        (
            "The café permit is on the public record. Now the City checks "
            "who decided, the map and a fee change."
        ),
    ]
    for index, step in enumerate(steps):
        assert step["path"].startswith("/")
        if step.get("kind") in {"intro", "bridge"}:
            assert step["target"] == ""
        else:
            assert step["target"]
        if step.get("kind") != "bridge":
            continue
        assert step["path"] == steps[index - 1]["path"]
        assert step["actor_id"] == ""
        assert step["persona"] == ""
        assert not step.get("muse")
        assert steps[index + 1]["kind"] == "intro"
        assert step["title"] != steps[index + 1]["title"]
    again = client.get("/tour/steps?path=story")
    assert again.status_code == 200
    assert again.json()["path"] == "story"
    assert again.json()["steps"] == steps


def test_the_route_serves_the_steps_of_every_path(client: TestClient) -> None:
    for key, path in tour_steps()["paths"].items():
        response = client.get(f"/tour/steps?path={key}")
        assert response.status_code == 200, key
        payload = response.json()
        assert payload["path"] == key
        assert len(payload["steps"]) == len(path["steps"])
        assert [item["key"] for item in payload["paths"]] == [item.key for item in PATHS]
        assert {item["key"] for item in payload["paths"]} == set(tour_steps()["paths"])


def test_the_route_refuses_a_path_that_does_not_exist(client: TestClient) -> None:
    response = client.get("/tour/steps?path=nonsense")
    assert response.status_code == 200
    assert response.json()["path"] == "cafe"


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
    script = SCRIPT.read_text(encoding="utf-8")
    assert 'method: "POST"' in script
    assert "/ui/actor" in script
    assert "/ui/actions/" not in script
    # The only requests the engine makes are the persona switch, the steps of
    # the path and the one copy the café path may offer.
    assert script.count("fetch(") == 3
    assert "/walkthrough/start-fresh" in script


def test_the_engine_starts_the_path_it_is_given() -> None:
    """A button that names a path starts that path."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "data-tour-start" in script
    assert "start(button.getAttribute(\"data-tour-start\") || \"\")" in script
    assert "?path=" in script


def test_the_engine_carries_the_auto_play_across_the_page_change() -> None:
    """The wish to play on travels with the state of the tour.

    The state of the tour lives in the session storage.  The wish to play on
    is part of it, so the screen the tour comes to starts the timer again and
    the viewer does not have to press the button a second time.
    """
    script = SCRIPT.read_text(encoding="utf-8")
    # The state of the tour names the wish to play on and the path it walks.
    assert re.search(r"var state = \{[^}]*playing:\s*false", script)
    assert "state.playing = true" in script
    assert re.search(r"var state = \{[^}]*path:\s*\"\"", script)
    # The resume reads the wish and the path back from the storage.
    assert "state.playing = !!saved.playing" in script
    assert "if (saved.path) state.path = saved.path;" in script
    # The change of the screen writes the state first and stops the timers of
    # the page afterwards: the wish crosses the change, the timers do not.
    body = re.search(r"function goTo\(number\) \{(.*?)\n  \}", script, re.S)
    assert body is not None
    assert body.group(1).index("persist()") < body.group(1).index("clearTimers()")


def test_the_engine_shows_what_the_auto_play_does() -> None:
    """The button says what it does, and the panel counts the step down."""
    script = SCRIPT.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    # The button says Auto-play when the tour is still and Pause when it plays.
    assert 'state.playing ? "Pause" : "Auto-play"' in script
    # The countdown stands beside the button and counts the seconds down.
    assert 'data-testid="tour-countdown"' in script
    assert "Next in " in script
    assert ".tour-countdown" in style
    assert ".tour-progress-fill" in style
    # The seconds are quiet for the screen reader; only the caption is told.
    assert 'aria-live="off"' in script
    assert 'aria-live="polite"' in script


def test_the_engine_keeps_the_reduced_motion_rule() -> None:
    """With reduced motion the tour does not play on its own."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "the system asks for reduced motion" in script
    body = re.search(r"function startAuto\(\) \{(.*?)\n  \}", script, re.S)
    assert body is not None
    assert "reducedMotion()" in body.group(1)


def test_the_engine_centres_a_story_step_and_marks_muse() -> None:
    """A step with no control is centred, and a Muse step shows the badge."""
    script = SCRIPT.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    assert "is-centred" in script
    assert 'data-testid="tour-muse-badge"' in script
    assert ">Muse<" in script
    assert ".tour-panel.is-centred" in style
    assert ".tour-panel:not(.is-centred)" in style
    body = re.search(r"function startAuto\(\) \{(.*?)\n  \}", script, re.S)
    assert body is not None
    assert "reducedMotion()" in body.group(1)
    assert "target" not in body.group(1)


def test_each_track_opens_on_its_own_story(paths: dict[str, dict]) -> None:
    """The fence is first. The café and the city each open on a story too."""
    for key in ("resident", "cafe", "city"):
        first = paths[key]["steps"][0]
        assert first.get("kind") == "intro", key
        assert first.get("target") == "", key
        assert "We are here because" in first["caption"], key
    assert "fence" in paths["resident"]["steps"][0]["title"].lower()
    assert paths["before"]["steps"][0].get("kind") != "intro"


def test_every_muse_step_names_what_muse_does(paths: dict[str, dict]) -> None:
    """Every Muse step names the surface and what Muse does there."""
    expected = {
        ("resident", "ask"): "help",
        ("resident", "check"): "presubmit",
        ("resident", "agent"): "intake",
        ("cafe", "steward"): "explain",
        ("cafe", "agent"): "intake",
        ("city", "whatif"): "policy",
    }
    found = {}
    for key, path in paths.items():
        for step in path["steps"]:
            if not step.get("muse"):
                assert not step.get("muse_line"), (key, step.get("id"))
                continue
            line = str(step.get("muse_line") or "")
            assert "Muse" in line, (key, step.get("id"))
            assert "Spark" not in line and "GPT" not in line and "Claude" not in line
            assert str(step.get("target") or "").strip(), (key, step.get("id"))
            found[(key, step["id"])] = step.get("muse_surface")
    assert found == expected


def test_muse_steps_name_the_recorded_replay_when_live_muse_is_off(
    client: TestClient, session: Session, settings
) -> None:
    """Live Muse is off in the tests, so every Muse step names the recorded replay."""
    from acme_city.applicant_help.config import load_config
    from acme_city.applicant_portal.presubmit import ASSISTANT_OFFLINE
    from acme_city.ui.guide_routes import INTAKE_REPLAY_LABEL, POLICY_REPLAY_LABEL
    from acme_city.ui.steward_assist_views import explain_state

    reviewer = (ROOT / "src" / "acme_city" / "ui" / "reviewer_views.py").read_text(encoding="utf-8")
    policy = (ROOT / "src" / "acme_city" / "ui" / "policy_routes.py").read_text(encoding="utf-8")
    assert INTAKE_REPLAY_LABEL in reviewer
    assert POLICY_REPLAY_LABEL in policy
    expected = {
        "help": load_config().replay_label,
        "presubmit": ASSISTANT_OFFLINE,
        "intake": INTAKE_REPLAY_LABEL,
        "explain": explain_state(session, settings)["note"],
        "policy": POLICY_REPLAY_LABEL,
    }
    payload = client.get("/tour/steps").json()
    surfaces = set()
    for step in payload["steps"]:
        note = str(step.get("replay_note") or "")
        if not step.get("muse"):
            assert note == "", step.get("id")
            continue
        surface = str(step.get("muse_surface") or "")
        surfaces.add(surface)
        assert "recorded replay" in note.lower(), step.get("id")
        assert expected[surface] in note, (step.get("id"), surface, note)
        assert "Muse" in str(step.get("muse_line") or "")
        for banned in ("Spark", "GPT", "Claude"):
            assert banned not in note
            assert banned not in str(step.get("muse_line") or "")
            assert banned not in str(step.get("caption") or "")
    assert surfaces == {"help", "presubmit", "intake", "explain", "policy"}


def test_the_engine_finishes_the_tour_at_the_last_step() -> None:
    """At the last step the auto-play stops and the panel says so."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "The tour is finished." in script
    body = re.search(r"function startAuto\(\) \{(.*?)\n  \}", script, re.S)
    assert body is not None
    assert "index >= steps.length - 1" in body.group(1)
