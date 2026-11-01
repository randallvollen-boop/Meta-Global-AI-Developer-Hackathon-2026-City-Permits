"""The tour opens from the landing and from the menu of the persona chip.

The button starts the first step of the tour, and the tour walks every step
on a desktop and on a phone without any help from the test.
"""

from __future__ import annotations

import pytest
from conftest import BrowserServer

#: The width of the tour in the browser, and the height of the screen.
VIEWPORTS = ({"width": 1280, "height": 900}, {"width": 390, "height": 844})


def steps_of(page, server: BrowserServer, path: str = "cafe") -> list[dict[str, str]]:
    """Return the steps of one path the server serves to the browser."""
    return page.request.get(f"{server.base_url}/tour/steps?path={path}").json()["steps"]


def wait_for_step(page, server: BrowserServer, step: dict[str, str]) -> None:
    """Wait until the tour shows the given step on its screen."""
    page.wait_for_url(f"{server.base_url}{step['path']}")
    page.wait_for_selector('[data-testid="tour-overlay"]:not([hidden])')
    page.wait_for_function(
        "(title) => { const element = document.querySelector('[data-testid=\"tour-title\"]');"
        " return element !== null && element.textContent.trim() === title; }",
        arg=step["title"],
    )


def test_the_button_of_the_landing_starts_the_first_step(page, server: BrowserServer) -> None:
    steps = steps_of(page, server)
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.locator('[data-testid="tour-start-landing"]').click()
    wait_for_step(page, server, steps[0])
    assert page.locator('[data-testid="tour-count"]').inner_text().strip() == (
        f"Step 1 of {len(steps)}"
    )
    assert page.recorded_errors == []


def test_the_button_of_a_path_card_on_the_landing_starts_that_path(
    page, server: BrowserServer
) -> None:
    """Every path on the landing opens its own tour."""
    steps = steps_of(page, server, "city")
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.locator('[data-testid="landing-path"][data-path="city"] [data-testid="landing-path-start"]').click()
    wait_for_step(page, server, steps[0])
    assert page.locator('[data-testid="tour-count"]').inner_text().strip() == (
        f"Step 1 of {len(steps)}"
    )
    assert page.recorded_errors == []


def test_the_button_of_the_staff_menu_starts_the_first_step(page, server: BrowserServer) -> None:
    """The tour opens from the menu of the chip in the staff frame."""
    steps = steps_of(page, server)
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.locator('button[data-persona="persona_data_steward"]').click()
    page.wait_for_url(f"{server.base_url}/steward")
    page.locator('[data-testid="persona-trigger"]').click()
    page.locator('[data-testid="tour-start-menu"]').click()
    wait_for_step(page, server, steps[0])
    assert page.recorded_errors == []


def test_the_button_of_the_city_menu_starts_the_first_step(page, server: BrowserServer) -> None:
    """The tour opens from the menu of the same chip in the City frame."""
    steps = steps_of(page, server)
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.locator('button[data-persona="persona_applicant"]').click()
    page.wait_for_url(f"{server.base_url}/city/")
    page.locator('.city-header [data-testid="persona-trigger"]').click()
    page.locator('.city-header [data-testid="tour-start-menu"]').click()
    wait_for_step(page, server, steps[0])
    assert page.recorded_errors == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1280", "390"])
def test_the_tour_walks_every_step_from_the_landing(
    page, server: BrowserServer, viewport
) -> None:
    """The tour walks every step on its own, on a desktop and on a phone."""
    page.set_viewport_size(viewport)
    steps = steps_of(page, server)
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.locator('[data-testid="tour-start-landing"]').click()
    for number, step in enumerate(steps, start=1):
        wait_for_step(page, server, step)
        assert page.locator('[data-testid="tour-caption"]').inner_text().strip() == step["caption"]
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
    page.locator('[data-testid="tour-next"]').click()
    assert page.locator('[data-testid="tour-overlay"]').is_hidden()
    assert page.recorded_errors == []
