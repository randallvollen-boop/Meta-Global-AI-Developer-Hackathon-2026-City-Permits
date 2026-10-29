"""The persona selector explains each persona and fits a phone."""

from __future__ import annotations

from conftest import BrowserServer


def test_each_persona_card_says_who_and_what_and_fits_390px(page, server: BrowserServer) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    cards = page.locator('[data-testid="persona-card"]')
    assert cards.count() == 4
    for index in range(cards.count()):
        card = cards.nth(index)
        assert card.locator(".persona-who").count() == 1
        assert card.locator(".persona-does").count() == 1
        assert card.locator("button[data-persona]").count() == 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.recorded_errors == []


def test_each_persona_card_shows_its_role_icon(page, server: BrowserServer) -> None:
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    icons = page.locator('[data-testid="persona-card"] img.persona-icon')
    assert icons.count() == 4
    for index in range(icons.count()):
        assert icons.nth(index).evaluate("img => img.complete && img.naturalWidth > 0")
