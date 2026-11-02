"""The permit life cycle page and the judge walkthrough open the real screens and fit a phone."""
# REQUIRES: UX-04, PER-03
# Every "Open as" button switches persona through the ordinary switch and
# lands on the screen it names, not on a fallback home.

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from acme_city.permits import lifecycle_map
from acme_city.ui.guide_views import PATHS, resolve_path
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


def _tracks():
    """The three tracks, in the order the page lists them."""
    return [path for path in PATHS if path.key != "before"]


def _track_boxes(page) -> list[dict[str, float | str]]:
    """Return the place of each track column."""
    return page.evaluate(
        """() => [...document.querySelectorAll('[data-testid="walkthrough-path"]')].map((el) => {
            const box = el.getBoundingClientRect();
            return { key: el.dataset.path, top: box.top, left: box.left, right: box.right };
        })"""
    )


def test_the_walkthrough_shows_one_card_for_every_path(page, server: BrowserServer) -> None:
    """The three tracks are columns. Before you start is one row above them."""
    page.goto(f"{server.base_url}/walkthrough", wait_until="domcontentloaded")
    tracks = _tracks()
    before = next(path for path in PATHS if path.key == "before")
    cards = page.locator('[data-testid="walkthrough-path"]')
    assert cards.count() == len(tracks)
    for index, path in enumerate(tracks):
        card = cards.nth(index)
        assert card.get_attribute("data-path") == path.key
        assert path.title in card.inner_text()
        assert path.one_line in card.inner_text()
        assert f"{path.minutes} minutes" in card.inner_text()
        assert card.locator('[data-testid="path-start"]').count() == 1
        assert card.locator('[data-testid="path-steps-link"]').count() == 1
        numbers = [
            card.locator(".guide-step-n").nth(step_index).inner_text().strip()
            for step_index in range(card.locator(".guide-step-n").count())
        ]
        assert numbers == [str(number) for number in range(1, len(path.steps) + 1)]
    steps = page.locator('[data-testid="walkthrough-step"]')
    assert steps.count() == sum(len(path.steps) for path in tracks)
    row = page.locator('[data-testid="walkthrough-before"]')
    assert row.count() == 1
    assert row.get_attribute("data-path") == before.key
    assert before.title in row.inner_text()
    assert before.one_line in page.content()
    assert f"{before.minutes} minutes" in row.inner_text()
    assert row.locator('[data-testid="path-start"]').count() == 1
    links = row.locator('[data-testid="walkthrough-link"]')
    assert links.count() == len(before.steps)
    for index, step in enumerate(before.steps):
        assert links.nth(index).inner_text().strip() == step.title
        assert links.nth(index).get_attribute("href") == step.path
    row_box = row.bounding_box()
    first = cards.first.bounding_box()
    assert row_box is not None and first is not None
    assert row_box["y"] < first["y"]
    assert page.recorded_errors == []


def test_the_tracks_sit_side_by_side_at_1280(page, server: BrowserServer) -> None:
    """At 1280 the three tracks share a top and run left to right."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{server.base_url}/walkthrough", wait_until="domcontentloaded")
    boxes = _track_boxes(page)
    assert [box["key"] for box in boxes] == [path.key for path in _tracks()]
    assert abs(boxes[0]["top"] - boxes[1]["top"]) <= 2
    assert abs(boxes[1]["top"] - boxes[2]["top"]) <= 2
    assert boxes[0]["left"] < boxes[1]["left"] < boxes[2]["left"]
    assert boxes[0]["right"] <= boxes[1]["left"] + 1
    assert boxes[1]["right"] <= boxes[2]["left"] + 1
    before = page.locator('[data-testid="walkthrough-before"]').bounding_box()
    assert before is not None
    assert before["y"] + before["height"] <= boxes[0]["top"] + 2
    # The row is one line. A wrapped row would be about twice as tall as its tallest item.
    row_line = page.evaluate(
        """() => {
            const kids = [...document.querySelectorAll('[data-testid="walkthrough-before"] > *')]
              .filter((el) => !el.classList.contains('visually-hidden'))
              .map((el) => el.getBoundingClientRect());
            const top = Math.min(...kids.map((box) => box.top));
            const bottom = Math.max(...kids.map((box) => box.bottom));
            const tallest = Math.max(...kids.map((box) => box.height));
            return { span: bottom - top, tallest: tallest };
        }"""
    )
    assert row_line["span"] <= row_line["tallest"] + 2, row_line
    assert page.recorded_errors == []


def test_the_tracks_stack_at_390_without_overflow(page, server: BrowserServer) -> None:
    """At 390 the tracks stack in the same order and the page does not overflow."""
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/walkthrough", wait_until="domcontentloaded")
    boxes = _track_boxes(page)
    assert [box["key"] for box in boxes] == [path.key for path in _tracks()]
    assert boxes[0]["top"] < boxes[1]["top"] < boxes[2]["top"]
    assert abs(boxes[0]["left"] - boxes[1]["left"]) <= 2
    assert abs(boxes[1]["left"] - boxes[2]["left"]) <= 2
    before = page.locator('[data-testid="walkthrough-before"]').bounding_box()
    assert before is not None
    assert before["y"] < boxes[0]["top"]
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


def test_each_track_start_opens_that_tracks_tour(page, server: BrowserServer) -> None:
    """Start on a track opens the tour of that track, not another path."""
    for path in _tracks():
        steps = page.request.get(f"{server.base_url}/tour/steps?path={path.key}").json()["steps"]
        assert steps
        page.goto(f"{server.base_url}/walkthrough", wait_until="networkidle")
        page.locator(
            f'[data-testid="walkthrough-path"][data-path="{path.key}"] [data-testid="path-start"]'
        ).click()
        page.wait_for_url(f"{server.base_url}{steps[0]['path']}")
        page.wait_for_selector('[data-testid="tour-overlay"]:not([hidden])')
        page.wait_for_function(
            "(title) => { const element = document.querySelector('[data-testid=\"tour-title\"]');"
            " return element !== null && element.textContent.trim() === title; }",
            arg=steps[0]["title"],
        )
        assert page.locator('[data-testid="tour-count"]').inner_text().strip() == (
            f"Step 1 of {len(steps)}"
        )
        assert page.locator('[data-testid="tour-path"]').inner_text().strip() == path.title
        page.evaluate("() => window.acmeTour.exit()")
    assert page.recorded_errors == []


def test_every_walkthrough_step_lands_on_its_screen(page, server: BrowserServer) -> None:
    """Every step of every path opens the screen it names."""
    page.goto(f"{server.base_url}/walkthrough", wait_until="domcontentloaded")
    for path in PATHS:
        for step in path.steps:
            page.goto(f"{server.base_url}/walkthrough", wait_until="domcontentloaded")
            expected_path = resolve_path(step.path)
            if step.persona:
                page.locator(
                    f'[data-testid="walkthrough-open"][data-next="{expected_path}"]'
                ).first.click()
                page.wait_for_load_state("domcontentloaded")
                assert urlparse(page.url).path == expected_path, step.title
                assert "moved_from" not in page.url, step.title
                if step.persona == "Applicant":
                    assert page.locator('[data-testid="applicant-account"]').count() == 1, step.title
                else:
                    assert page.locator('[data-testid="acting-persona"]').first.inner_text().startswith(
                        step.persona
                    ), step.title
            else:
                response = page.request.get(f"{server.base_url}{expected_path}")
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
