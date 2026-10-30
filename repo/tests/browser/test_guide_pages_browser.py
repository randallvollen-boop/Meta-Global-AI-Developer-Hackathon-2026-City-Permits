"""The permit life cycle page and the judge walkthrough open the real screens and fit a phone."""
# REQUIRES: UX-04, PER-03
# Every "Open as" button switches persona through the ordinary switch and
# lands on the screen it names, not on a fallback home.

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from acme_city.permits import lifecycle_map
from acme_city.ui.guide_views import WALKTHROUGH
from conftest import BrowserServer


def _fits(page) -> bool:
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


@pytest.mark.parametrize("path", ["/lifecycle", "/walkthrough"])
def test_guide_pages_open_signed_out_and_fit_390px(page, server: BrowserServer, path: str) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    response = page.goto(f"{server.base_url}{path}", wait_until="networkidle")
    assert response is not None and response.ok
    assert _fits(page)
    assert page.recorded_errors == []


def test_lifecycle_lists_every_status_with_its_moves(page, server: BrowserServer) -> None:
    page.goto(f"{server.base_url}/lifecycle", wait_until="domcontentloaded")
    cards = page.locator('[data-testid="lifecycle-status"]')
    assert [cards.nth(i).get_attribute("data-status") for i in range(cards.count())] == [
        item.key for item in lifecycle_map.STATUSES
    ]
    assert page.locator('[data-testid="lifecycle-move"]').count() == sum(
        len(move.sources) for move in lifecycle_map.MOVES
    )
    assert page.locator('[data-testid="lifecycle-main-path"] li').count() == 5
    # A person move always names a persona; none says the fallback.
    assert "no persona in this demonstration" not in page.locator("main").inner_text()


def test_lifecycle_examples_open_the_permit_workspace(page, server: BrowserServer) -> None:
    page.goto(f"{server.base_url}/lifecycle", wait_until="domcontentloaded")
    buttons = page.locator('[data-testid="lifecycle-example"]')
    assert buttons.count() >= 1
    targets = [buttons.nth(i).get_attribute("data-next") for i in range(buttons.count())]
    for target in targets:
        page.goto(f"{server.base_url}/lifecycle", wait_until="domcontentloaded")
        page.locator(f'[data-testid="lifecycle-example"][data-next="{target}"]').click()
        page.wait_for_load_state("domcontentloaded")
        assert urlparse(page.url).path == target
        assert "moved_from" not in page.url


def test_every_walkthrough_step_lands_on_its_screen(page, server: BrowserServer) -> None:
    page.goto(f"{server.base_url}/walkthrough", wait_until="domcontentloaded")
    assert page.locator('[data-testid="walkthrough-step"]').count() == len(WALKTHROUGH)
    for step in WALKTHROUGH:
        page.goto(f"{server.base_url}/walkthrough", wait_until="domcontentloaded")
        if step.persona:
            page.locator(f'[data-testid="walkthrough-open"][data-next="{step.path}"]').first.click()
            page.wait_for_load_state("domcontentloaded")
            assert urlparse(page.url).path == step.path, step.title
            assert "moved_from" not in page.url, step.title
        else:
            response = page.request.get(f"{server.base_url}{step.path}")
            assert response.ok, step.title
    assert page.recorded_errors == []


def test_the_persona_selector_points_to_both_guides(page, server: BrowserServer) -> None:
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    links = page.locator('[data-testid="guide-links"] a')
    assert sorted(links.nth(i).get_attribute("href") for i in range(links.count())) == ["/lifecycle", "/walkthrough"]
