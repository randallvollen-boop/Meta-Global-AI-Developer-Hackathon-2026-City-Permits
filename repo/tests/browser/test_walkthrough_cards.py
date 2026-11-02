"""The cards of the paths: the tour starts, the steps open and the copy is made.

The landing and the walkthrough page carry one card for every path.  Each
card offers the tour of that path, the written steps of that path and, for
the café, the one button that writes: Start fresh.
"""
# REQUIRES: UX-04, SEC-02
# Every button of a card does what it says.

from __future__ import annotations

import re

from conftest import BrowserServer


def wait_for_the_copy(page, server: BrowserServer) -> str:
    """Wait until the walkthrough opens the copy the visitor made."""
    page.wait_for_url(re.compile(r"/walkthrough\?case=app_judge_"))
    notice = page.locator('[data-testid="judge-copy-notice"]')
    notice.wait_for()
    return notice.inner_text()


def test_the_start_button_of_the_landing_opens_the_tour_of_that_path(
    page, server: BrowserServer
) -> None:
    """The Start button of a card opens the tour of that path."""
    steps = page.request.get(f"{server.base_url}/tour/steps?path=resident").json()["steps"]
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.locator(
        '[data-testid="landing-path"][data-path="resident"] [data-testid="landing-path-start"]'
    ).click()
    page.wait_for_url(f"{server.base_url}{steps[0]['path']}")
    page.wait_for_selector('[data-testid="tour-overlay"]:not([hidden])')
    assert page.locator('[data-testid="tour-count"]').inner_text().strip() == (
        f"Step 1 of {len(steps)}"
    )
    assert page.recorded_errors == []


def test_the_steps_button_of_the_landing_opens_the_written_steps(
    page, server: BrowserServer
) -> None:
    """The Steps button of a card opens the path on the walkthrough page."""
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.locator(
        '[data-testid="landing-path"][data-path="city"] [data-testid="landing-path-steps"]'
    ).click()
    page.wait_for_url(f"{server.base_url}/walkthrough#path-city")
    page.wait_for_selector('[data-testid="walkthrough-path"][data-path="city"]')
    card = page.locator('[data-testid="walkthrough-path"][data-path="city"]')
    assert card.count() == 1
    assert card.locator('[data-testid="walkthrough-step"]').count() >= 1
    assert page.recorded_errors == []


def test_the_steps_button_of_the_walkthrough_page_opens_the_written_steps(
    page, server: BrowserServer
) -> None:
    """The Steps button of a card jumps to the steps of that path."""
    page.goto(f"{server.base_url}/walkthrough", wait_until="networkidle")
    page.locator(
        '[data-testid="walkthrough-path"][data-path="resident"] [data-testid="path-steps-link"]'
    ).click()
    page.wait_for_url(f"{server.base_url}/walkthrough#path-steps-resident")
    card = page.locator('[data-testid="walkthrough-path"][data-path="resident"]')
    # Changed deliberately (applicant notices): the resident track adds the
    # messages step, so the card lists five written steps.
    assert card.locator('[data-testid="walkthrough-step"]').count() == 5
    assert page.recorded_errors == []


def test_the_start_fresh_button_of_the_café_card_makes_a_copy(
    page, server: BrowserServer
) -> None:
    """The one button that writes makes a copy of the café case."""
    page.goto(f"{server.base_url}/walkthrough", wait_until="networkidle")
    with page.expect_response(
        lambda response: "/walkthrough/start-fresh" in response.url
    ) as posted:
        page.locator(
            '[data-testid="walkthrough-path"][data-path="cafe"] [data-testid="path-fresh"]'
        ).click()
    assert posted.value.status == 303
    notice = wait_for_the_copy(page, server)
    assert "CAFE-2026-" in notice
    assert page.recorded_errors == []


def test_the_start_fresh_button_of_the_landing_makes_a_copy(
    page, server: BrowserServer
) -> None:
    """The landing offers the same button as the walkthrough page."""
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    with page.expect_response(
        lambda response: "/walkthrough/start-fresh" in response.url
    ) as posted:
        page.locator('[data-testid="landing-path-fresh"]').click()
    assert posted.value.status == 303
    notice = wait_for_the_copy(page, server)
    assert "CAFE-2026-" in notice
    assert page.recorded_errors == []


def test_the_walkthrough_of_the_judge_opens_the_copy(page, server: BrowserServer) -> None:
    """The tour of the café path opens the copy the judge made."""
    page.goto(f"{server.base_url}/walkthrough", wait_until="networkidle")
    with page.expect_response(
        lambda response: "/walkthrough/start-fresh" in response.url
    ):
        page.locator(
            '[data-testid="walkthrough-path"][data-path="cafe"] [data-testid="path-fresh"]'
        ).click()
    wait_for_the_copy(page, server)

    steps = page.request.get(f"{server.base_url}/tour/steps?path=cafe").json()["steps"]
    screens = [step["path"] for step in steps]
    assert any(screen.startswith("/permits/app_judge_") for screen in screens), screens
