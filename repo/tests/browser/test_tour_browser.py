"""The guided tour walks every step and every control of it works.

The tour switches persona, opens the real screen, rings the control and
explains it.  The browser reads the steps from the server, so the test walks
the same list the tour walks.

The engine is loaded here by hand: the frames of the application carry the
script from the entry-point slice, and this test drives the engine itself.
"""

from __future__ import annotations

import re

import pytest
from conftest import BrowserServer

#: The width of the tour in the browser, and the height of the screen.
VIEWPORTS = ({"width": 1280, "height": 900}, {"width": 390, "height": 844})

#: The length of one step of the auto-play in the tests.  The ordinary tour
#: waits nine seconds; the test hook shortens it, and the hook travels with
#: the state of the tour, so it holds across the change of the screen.
AUTO_PLAY_MS = 2000


def load_engine(page, server: BrowserServer) -> None:
    """Load the tour engine on the page that is open."""
    page.add_script_tag(url=f"{server.base_url}/ui/static/tour.js")


def wait_for_step(page, server: BrowserServer, step: dict[str, str]) -> None:
    """Wait until the tour shows the given step on its screen."""
    page.wait_for_url(f"{server.base_url}{step['path']}")
    load_engine(page, server)
    page.wait_for_selector('[data-testid="tour-overlay"]:not([hidden])')
    page.wait_for_function(
        "(title) => { const element = document.querySelector('[data-testid=\"tour-title\"]');"
        " return element !== null && element.textContent.trim() === title; }",
        arg=step["title"],
    )


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1280", "390"])
def test_the_tour_walks_every_step(page, server: BrowserServer, viewport) -> None:
    page.set_viewport_size(viewport)
    steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
    assert steps
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    load_engine(page, server)
    page.evaluate("() => window.acmeTour.start()")
    for number, step in enumerate(steps, start=1):
        wait_for_step(page, server, step)
        assert page.locator('[data-testid="tour-count"]').inner_text().strip() == (
            f"Step {number} of {len(steps)}"
        )
        assert page.locator('[data-testid="tour-caption"]').inner_text().strip() == step["caption"]
        # The control of the step is ringed, not hidden.
        assert page.locator('[data-testid="tour-ring"]').is_visible()
        assert page.evaluate(
            """(selector) => { const target = document.querySelector(selector);
                 const ring = document.querySelector('[data-testid="tour-ring"]');
                 if (!target || !ring) return false;
                 const place = target.getBoundingClientRect();
                 const marked = ring.getBoundingClientRect();
                 return Math.abs(marked.top - place.top) < 12
                   && Math.abs(marked.left - place.left) < 12; }""",
            step["target"],
        )
        if number < len(steps):
            page.locator('[data-testid="tour-next"]').click()
    # The last step finishes the tour.
    page.locator('[data-testid="tour-next"]').click()
    assert page.locator('[data-testid="tour-overlay"]').is_hidden()
    assert page.recorded_errors == []


def test_the_back_button_returns_to_the_previous_step(page, server: BrowserServer) -> None:
    steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    load_engine(page, server)
    page.evaluate("() => window.acmeTour.start()")
    wait_for_step(page, server, steps[0])
    assert page.locator('[data-testid="tour-back"]').is_disabled()
    page.locator('[data-testid="tour-next"]').click()
    wait_for_step(page, server, steps[1])
    page.locator('[data-testid="tour-back"]').click()
    wait_for_step(page, server, steps[0])
    assert page.recorded_errors == []


def test_the_auto_play_button_pauses_and_resumes(page, server: BrowserServer) -> None:
    steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    load_engine(page, server)
    page.evaluate("() => window.acmeTour.start()")
    wait_for_step(page, server, steps[0])
    play = page.locator('[data-testid="tour-play"]')
    assert play.inner_text().strip() == "Auto-play"
    play.click()
    assert play.inner_text().strip() == "Pause"
    play.click()
    assert play.inner_text().strip() == "Auto-play"
    assert page.recorded_errors == []


def test_the_auto_play_keeps_playing_across_the_screen_changes(
    page, server: BrowserServer
) -> None:
    """Auto-play walks on by itself: no second click is needed."""
    steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.evaluate("(ms) => window.acmeTour.setInterval(ms)", AUTO_PLAY_MS)
    # The tour opens from the landing, the way a reader opens it.
    page.locator('[data-testid="tour-start-landing"]').click()
    wait_for_step(page, server, steps[0])
    play = page.locator('[data-testid="tour-play"]')
    assert play.inner_text().strip() == "Auto-play"
    play.click()
    assert play.inner_text().strip() == "Pause"
    # The countdown of the step stands beside the button, and it counts down.
    countdown = page.locator('[data-testid="tour-countdown"]')
    assert countdown.is_visible()
    first = countdown.inner_text().strip()
    assert re.fullmatch(r"Next in \d+ s", first), first
    page.wait_for_function(
        "(first) => { const element = document.querySelector('[data-testid=\"tour-countdown\"]');"
        " return element !== null && element.textContent.trim() !== first; }",
        arg=first,
    )
    # The thin bar fills while the step waits.
    assert page.locator('[data-testid="tour-progress"]').is_visible()
    width = page.wait_for_function(
        """() => { const element = document.querySelector('[data-testid="tour-progress-fill"]');
             if (!element) return null;
             const box = element.getBoundingClientRect();
             return box.width > 0 ? box.width : null; }"""
    ).json_value()
    assert width > 0
    # The tour crosses the change of the screen on its own, and it plays on
    # on the screen it comes to.
    wait_for_step(page, server, steps[1])
    assert page.locator('[data-testid="tour-play"]').inner_text().strip() == "Pause"
    assert page.locator('[data-testid="tour-countdown"]').is_visible()
    wait_for_step(page, server, steps[2])
    assert page.locator('[data-testid="tour-play"]').inner_text().strip() == "Pause"
    assert page.locator('[data-testid="tour-countdown"]').is_visible()
    assert page.recorded_errors == []


def test_pause_stops_the_tour_and_the_pause_survives_a_reload(
    page, server: BrowserServer
) -> None:
    """Pause stops the tour, and the tour stays paused after a reload."""
    steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.evaluate("(ms) => window.acmeTour.setInterval(ms)", AUTO_PLAY_MS)
    page.evaluate("() => window.acmeTour.start()")
    wait_for_step(page, server, steps[0])
    play = page.locator('[data-testid="tour-play"]')
    play.click()
    assert play.inner_text().strip() == "Pause"
    play.click()
    assert play.inner_text().strip() == "Auto-play"
    assert page.locator('[data-testid="tour-countdown"]').is_hidden()
    # The pause travels with the tour: the reload does not start it again.
    page.reload(wait_until="networkidle")
    page.wait_for_selector('[data-testid="tour-overlay"]:not([hidden])')
    assert page.locator('[data-testid="tour-play"]').inner_text().strip() == "Auto-play"
    assert page.locator('[data-testid="tour-countdown"]').is_hidden()
    # The tour stays where it is: it does not walk on by itself.
    page.wait_for_timeout(AUTO_PLAY_MS + 1000)
    assert page.locator('[data-testid="tour-count"]').inner_text().strip() == (
        f"Step 1 of {len(steps)}"
    )
    assert page.recorded_errors == []


def test_next_and_back_keep_the_tour_playing(page, server: BrowserServer) -> None:
    """Next and Back move the tour on; they do not stop the auto-play."""
    steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    # A long step gives the test room to read the panel before the tour moves.
    page.evaluate("(ms) => window.acmeTour.setInterval(ms)", 5000)
    page.evaluate("() => window.acmeTour.start()")
    wait_for_step(page, server, steps[0])
    page.locator('[data-testid="tour-play"]').click()
    assert page.locator('[data-testid="tour-play"]').inner_text().strip() == "Pause"
    # Next moves the tour on, and the tour keeps playing there.
    page.locator('[data-testid="tour-next"]').click()
    wait_for_step(page, server, steps[1])
    assert page.locator('[data-testid="tour-play"]').inner_text().strip() == "Pause"
    assert page.locator('[data-testid="tour-countdown"]').is_visible()
    # Back moves the tour back, and the tour keeps playing there too.
    page.locator('[data-testid="tour-back"]').click()
    wait_for_step(page, server, steps[0])
    assert page.locator('[data-testid="tour-play"]').inner_text().strip() == "Pause"
    assert page.locator('[data-testid="tour-countdown"]').is_visible()
    assert page.recorded_errors == []


def test_the_length_of_the_step_may_change_while_the_tour_plays(
    page, server: BrowserServer
) -> None:
    """The step of the auto-play follows the hook, whenever the hook is set."""
    steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.evaluate("() => window.acmeTour.start()")
    wait_for_step(page, server, steps[0])
    page.locator('[data-testid="tour-play"]').click()
    assert page.locator('[data-testid="tour-play"]').inner_text().strip() == "Pause"
    # The hook comes after the tour has begun to play.
    page.evaluate("(ms) => window.acmeTour.setInterval(ms)", AUTO_PLAY_MS)
    wait_for_step(page, server, steps[1])
    assert page.locator('[data-testid="tour-play"]').inner_text().strip() == "Pause"
    assert page.recorded_errors == []


def test_the_length_of_the_step_may_come_from_the_tour_root(
    page, server: BrowserServer
) -> None:
    """The attribute on the root of the tour shortens the step."""
    steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.evaluate("() => window.acmeTour.start()")
    wait_for_step(page, server, steps[0])
    page.evaluate(
        "(ms) => { const root = document.querySelector('[data-testid=\"tour-overlay\"]');"
        " root.setAttribute('data-tour-interval', ms); }",
        AUTO_PLAY_MS,
    )
    page.locator('[data-testid="tour-play"]').click()
    # The tour moves on in the short step, and it keeps the short step on the
    # screen it comes to.
    wait_for_step(page, server, steps[1])
    assert page.locator('[data-testid="tour-play"]').inner_text().strip() == "Pause"
    assert page.recorded_errors == []


def test_the_countdown_fits_on_a_phone(page, server: BrowserServer) -> None:
    """The countdown stands beside the button on a small screen too."""
    steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.evaluate("(ms) => window.acmeTour.setInterval(ms)", AUTO_PLAY_MS)
    page.evaluate("() => window.acmeTour.start()")
    wait_for_step(page, server, steps[0])
    page.locator('[data-testid="tour-play"]').click()
    assert page.locator('[data-testid="tour-countdown"]').is_visible()
    # The panel stays on the screen, and the controls stay inside it.
    panel = page.locator('[data-testid="tour-panel"]').bounding_box()
    assert panel["x"] >= 0
    assert panel["x"] + panel["width"] <= 391
    controls = page.locator(".tour-controls").bounding_box()
    assert controls["x"] >= panel["x"]
    assert controls["x"] + controls["width"] <= panel["x"] + panel["width"] + 1
    assert page.recorded_errors == []


def test_the_auto_play_stops_at_the_last_step(page, server: BrowserServer) -> None:
    """The tour plays on to its last step, and there it stops."""
    steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.evaluate("(ms) => window.acmeTour.setInterval(ms)", AUTO_PLAY_MS)
    page.evaluate("() => window.acmeTour.start()")
    wait_for_step(page, server, steps[0])
    page.locator('[data-testid="tour-play"]').click()
    # The tour walks on by itself to the last step of the story.
    wait_for_step(page, server, steps[-1])
    # There the auto-play stops, and the panel says the tour is finished.
    assert "finished" in page.locator('[data-testid="tour-note"]').inner_text()
    assert page.locator('[data-testid="tour-play"]').inner_text().strip() == "Auto-play"
    assert page.locator('[data-testid="tour-countdown"]').is_hidden()
    # It stays on the last step: it does not close itself and does not move on.
    page.wait_for_timeout(AUTO_PLAY_MS + 1000)
    assert page.locator('[data-testid="tour-count"]').inner_text().strip() == (
        f"Step {len(steps)} of {len(steps)}"
    )
    assert page.locator('[data-testid="tour-overlay"]').is_visible()
    assert page.recorded_errors == []


def test_the_exit_button_closes_the_tour(page, server: BrowserServer) -> None:
    steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    load_engine(page, server)
    page.evaluate("() => window.acmeTour.start()")
    wait_for_step(page, server, steps[0])
    page.locator('[data-testid="tour-exit"]').click()
    assert page.locator('[data-testid="tour-overlay"]').is_hidden()
    # The tour forgets its place: a reload opens no tour.
    page.reload(wait_until="networkidle")
    load_engine(page, server)
    assert page.locator('[data-testid="tour-overlay"]').count() == 0
    assert page.recorded_errors == []


def test_the_start_button_opens_the_first_step(page, server: BrowserServer) -> None:
    steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    load_engine(page, server)
    page.evaluate(
        """() => { const button = document.createElement('button');
             button.type = 'button';
             button.setAttribute('data-tour-start', '');
             button.setAttribute('data-testid', 'tour-start');
             button.textContent = 'Take the tour';
             document.body.appendChild(button); }"""
    )
    page.locator('[data-testid="tour-start"]').click()
    wait_for_step(page, server, steps[0])
    assert page.recorded_errors == []


def test_auto_play_is_off_when_the_system_asks_for_reduced_motion(
    browser, server: BrowserServer
) -> None:
    context = browser.new_context(
        viewport={"width": 1280, "height": 900}, reduced_motion="reduce"
    )
    page = context.new_page()
    try:
        steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
        page.goto(f"{server.base_url}/select", wait_until="networkidle")
        load_engine(page, server)
        page.evaluate("() => window.acmeTour.start()")
        wait_for_step(page, server, steps[0])
        play = page.locator('[data-testid="tour-play"]')
        assert play.is_disabled()
        # A disabled button says why, beside it.
        note = page.locator('[data-testid="tour-note"]')
        assert note.is_visible()
        assert "reduced motion" in note.inner_text()
    finally:
        context.close()


def test_the_auto_play_stays_off_with_reduced_motion(
    browser, server: BrowserServer
) -> None:
    """The tour does not play on its own when the system asks for less motion."""
    context = browser.new_context(
        viewport={"width": 1280, "height": 900}, reduced_motion="reduce"
    )
    page = context.new_page()
    try:
        steps = page.request.get(f"{server.base_url}/tour/steps").json()["steps"]
        page.goto(f"{server.base_url}/select", wait_until="networkidle")
        page.evaluate("(ms) => window.acmeTour.setInterval(ms)", AUTO_PLAY_MS)
        page.evaluate("() => window.acmeTour.start()")
        wait_for_step(page, server, steps[0])
        play = page.locator('[data-testid="tour-play"]')
        assert play.inner_text().strip() == "Auto-play"
        assert play.is_disabled()
        # No countdown stands beside the button: the tour is not playing.
        assert page.locator('[data-testid="tour-countdown"]').is_hidden()
        # The tour stays on the first step: it does not walk on by itself.
        page.wait_for_timeout(AUTO_PLAY_MS + 1000)
        assert page.locator('[data-testid="tour-count"]').inner_text().strip() == (
            f"Step 1 of {len(steps)}"
        )
    finally:
        context.close()
