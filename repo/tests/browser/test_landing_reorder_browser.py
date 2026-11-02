"""The landing shows the five personas in one row and keeps the video closed.

The card of a persona names the persona and opens the screen that persona
works in.  The video sits below the cards as a title card: nothing of it is
loaded until the card is opened.
"""

from __future__ import annotations

import pytest
from conftest import BrowserServer

#: The five personas, the one sentence on each card, and the screen each opens.
PERSONAS = (
    ("persona_applicant", "Applicant", "A resident who applies for a permit and tracks it.", "/city/"),
    ("persona_agent_operator", "Agent Operator", "Runs the agents that read and route new applications.", "/agents"),
    ("persona_data_steward", "Data Steward", "Links people and properties so every record matches.", "/steward"),
    ("persona_permit_reviewer", "Permit Reviewer", "Checks each case and records the decision.", "/queue"),
    ("persona_city_administrator", "City Administrator", "Sets the rules and fees and watches the whole system.", "/overview"),
)


def test_the_five_personas_are_in_one_row_inside_the_first_viewport(page, server: BrowserServer) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    cards = page.locator('[data-testid="persona-card"]')
    buttons = page.locator('[data-testid="persona-card"] button[data-persona]')
    assert buttons.count() == 5
    tops = []
    for index in range(buttons.count()):
        card = cards.nth(index).bounding_box()
        box = buttons.nth(index).bounding_box()
        assert card is not None and box is not None
        tops.append(round(card["y"]))
        assert box["y"] >= 0, "the button is above the fold"
        assert box["y"] + box["height"] <= 800, "the button needs a scroll to be seen"
    assert len(set(tops)) == 1, f"the cards are not in one row: {tops}"
    assert page.recorded_errors == []


@pytest.mark.parametrize("width", (1100, 1280, 1440))
def test_every_persona_button_fits_inside_its_card(page, server: BrowserServer, width: int) -> None:
    """The button of a card never reaches into the next card."""
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    cards = page.locator('[data-testid="persona-card"]')
    for index in range(cards.count()):
        card = cards.nth(index).bounding_box()
        button = cards.nth(index).locator("button[data-persona]").bounding_box()
        assert card is not None and button is not None
        assert button["x"] >= card["x"] - 1, (width, index)
        assert button["x"] + button["width"] <= card["x"] + card["width"] + 1, (width, index)
    assert page.recorded_errors == []


def test_every_persona_card_opens_the_screen_of_that_persona(page, server: BrowserServer) -> None:
    for actor_id, label, line, target in PERSONAS:
        page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
        # The card says in one sentence who the person is before it is pressed.
        card = page.locator('[data-testid="persona-card"]').filter(
            has=page.get_by_role("heading", name=label, exact=True)
        )
        assert card.count() == 1, label
        shown = card.locator('[data-testid="persona-line"]')
        assert shown.count() == 1, label
        assert " ".join(shown.inner_text().split()) == line, label
        page.locator(f'button[data-persona="{actor_id}"]').click()
        page.wait_for_url(f"{server.base_url}{target}")
        assert label in page.content(), (actor_id, page.url)
    assert page.recorded_errors == []


def test_the_video_waits_for_the_title_card_and_then_plays(page, server: BrowserServer) -> None:
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    asked: list[str] = []
    page.on("request", lambda request: asked.append(request.url))
    video = page.locator('[data-testid="demo-video-player"]')
    assert video.count() == 1
    # The player is inside the disclosure: it is not on the page yet.
    assert not video.is_visible()
    assert page.locator('[data-testid="demo-video-title"]').inner_text().strip() != ""
    assert not [url for url in asked if url.endswith(".mp4")]

    page.locator('[data-testid="demo-video-title"]').click()
    assert video.is_visible()
    page.evaluate(
        """() => { const video = document.querySelector('[data-testid="demo-video-player"]');
             video.play().catch(() => {}); }"""
    )
    page.wait_for_timeout(1000)
    assert [url for url in asked if url.endswith(".mp4")]
    assert page.evaluate(
        """() => { const video = document.querySelector('[data-testid="demo-video-player"]');
             return video.controls && !video.autoplay && video.preload === 'none'; }"""
    )
    assert page.recorded_errors == []
