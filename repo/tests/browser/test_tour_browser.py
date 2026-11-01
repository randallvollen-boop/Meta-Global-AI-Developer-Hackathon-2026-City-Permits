"""The guided tour walks every step and every control of it works.

The tour switches persona, opens the real screen, rings the control and
explains it.  The browser reads the steps from the server, so the test walks
the same list the tour walks.

The engine is loaded here by hand: the frames of the application carry the
script from the entry-point slice, and this test drives the engine itself.
"""

from __future__ import annotations

import pytest
from conftest import BrowserServer

#: The width of the tour in the browser, and the height of the screen.
VIEWPORTS = ({"width": 1280, "height": 900}, {"width": 390, "height": 844})


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
