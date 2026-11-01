"""The permit life cycle page and the judge walkthrough open the real screens and fit a phone."""
# REQUIRES: UX-04, PER-03
# Every "Open as" button switches persona through the ordinary switch and
# lands on the screen it names, not on a fallback home.

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from acme_city.permits import lifecycle_map
from acme_city.ui.guide_views import PATHS
from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

PERSONAS = (
    "persona_applicant",
    "persona_data_steward",
    "persona_permit_reviewer",
    "persona_city_administrator",
    "persona_agent_operator",
)
CONTROLS = '[data-testid="open-as"], [data-testid="lifecycle-example"], [data-testid="walkthrough-open"], [data-testid="walkthrough-link"]'


@pytest.mark.parametrize("actor_id", ("",) + PERSONAS)
@pytest.mark.parametrize("path", ["/lifecycle", "/walkthrough"])
def test_guide_pages_fit_390px_for_every_persona_and_signed_out(
    page, server: BrowserServer, login, path: str, actor_id: str
) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    if actor_id:
        login(actor_id)
    response = page.goto(f"{server.base_url}{path}", wait_until="networkidle")
    assert response is not None and response.ok
    assert_no_horizontal_overflow(page)
    if path == "/lifecycle":
        summaries = page.locator('details:has([data-testid="lifecycle-example"]) > summary')
        for index in range(summaries.count()):
            summaries.nth(index).click()
    controls = page.locator(CONTROLS)
    assert controls.count() >= 1
    for index in range(controls.count()):
        assert_not_covered(page, controls.nth(index))
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
        page.locator(
            f'details:has([data-testid="lifecycle-example"][data-next="{target}"]) > summary'
        ).click()
        page.locator(f'[data-testid="lifecycle-example"][data-next="{target}"]').click()
        page.wait_for_load_state("domcontentloaded")
        assert urlparse(page.url).path == target
        assert "moved_from" not in page.url
        assert page.locator('[data-testid="error-panel"]').count() == 0


def test_the_walkthrough_shows_one_card_for_every_path(page, server: BrowserServer) -> None:
    """The page offers the paths, each with its title, its line and its minutes."""
    page.goto(f"{server.base_url}/walkthrough", wait_until="domcontentloaded")
    cards = page.locator('[data-testid="walkthrough-path"]')
    assert cards.count() == len(PATHS)
    for index, path in enumerate(PATHS):
        card = cards.nth(index)
        assert card.get_attribute("data-path") == path.key
        assert path.title in card.inner_text()
        assert path.one_line in card.inner_text()
        assert f"{path.minutes} minutes" in card.inner_text()
        assert card.locator('[data-testid="path-start"]').count() == 1
        assert card.locator('[data-testid="path-steps-link"]').count() == 1
    # Every step of every path is on the page, with its words.
    steps = page.locator('[data-testid="walkthrough-step"]')
    assert steps.count() == sum(len(path.steps) for path in PATHS)
    assert page.recorded_errors == []


def test_every_walkthrough_step_lands_on_its_screen(page, server: BrowserServer) -> None:
    """Every step of every path opens the screen it names."""
    page.goto(f"{server.base_url}/walkthrough", wait_until="domcontentloaded")
    for path in PATHS:
        for step in path.steps:
            page.goto(f"{server.base_url}/walkthrough", wait_until="domcontentloaded")
            if step.persona:
                page.locator(
                    f'[data-testid="walkthrough-open"][data-next="{step.path}"]'
                ).first.click()
                page.wait_for_load_state("domcontentloaded")
                assert urlparse(page.url).path == step.path, step.title
                assert "moved_from" not in page.url, step.title
                if step.persona == "Applicant":
                    assert page.locator('[data-testid="applicant-account"]').count() == 1, step.title
                else:
                    assert page.locator('[data-testid="acting-persona"]').first.inner_text().startswith(
                        step.persona
                    ), step.title
            else:
                response = page.request.get(f"{server.base_url}{step.path}")
                assert response.ok, step.title
    assert page.recorded_errors == []


def test_the_persona_selector_points_to_both_guides(page, server: BrowserServer) -> None:
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    links = page.locator('[data-testid="guide-links"] a')
    assert sorted(links.nth(i).get_attribute("href") for i in range(links.count())) == [
        "/lifecycle",
        "/walkthrough",
    ]


def test_the_landing_offers_the_paths_under_the_personas(page, server: BrowserServer) -> None:
    """The landing offers one card for every path, under the personas."""
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    cards = page.locator('[data-testid="landing-path"]')
    assert cards.count() == len(PATHS)
    personas = page.locator('[data-testid="persona-card"]')
    assert personas.count() >= 1
    for index, path in enumerate(PATHS):
        card = cards.nth(index)
        assert card.get_attribute("data-path") == path.key
        assert path.title in card.inner_text()
        assert path.one_line in card.inner_text()
        assert card.locator('[data-testid="landing-path-start"]').count() == 1
        assert card.locator('[data-testid="landing-path-steps"]').count() == 1
    # The café card carries the one button that writes.
    fresh = page.locator('[data-testid="landing-path-fresh"]')
    assert fresh.count() == 1
    assert page.recorded_errors == []
