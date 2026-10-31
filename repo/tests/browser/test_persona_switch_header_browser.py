"""The persona menu in the top right of the staff frame, in the browser."""
# REQUIRES: UX-01, PER-04

from __future__ import annotations

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow

#: The five selectable personas and the home each one lands on.
PERSONAS = (
    ("persona_applicant", "/city/"),
    ("persona_agent_operator", "/agents"),
    ("persona_data_steward", "/steward"),
    ("persona_permit_reviewer", "/queue"),
    ("persona_city_administrator", "/overview"),
)


def test_the_chip_names_the_persona_that_acts(page, server: BrowserServer, login) -> None:
    """The chip in the top right shows the acting persona."""
    login("persona_data_steward")
    trigger = page.locator('[data-testid="persona-trigger"]')
    assert trigger.is_visible()
    assert "Data Steward" in page.locator('[data-testid="acting-persona"]').inner_text()
    # The menu is closed until the chip is pressed, and the browser does not
    # paint it before that.
    assert page.evaluate(
        "() => document.querySelector('[data-testid=\"demo-switch\"]').checkVisibility()"
    ) is False


@pytest.mark.parametrize(("actor_id", "home"), PERSONAS)
def test_each_persona_item_switches_and_lands_on_its_home(
    page, server: BrowserServer, login, actor_id: str, home: str
) -> None:
    """Clicking a persona names it as the acting persona and opens its home."""
    login("persona_data_steward")
    page.locator('[data-testid="persona-trigger"]').click()
    page.locator(f'[data-demo-persona="{actor_id}"]').click()
    page.wait_for_url(f"{server.base_url}{home}*")
    assert page.url.split("?")[0].endswith(home), page.url


def test_the_menu_works_with_the_keyboard(page, server: BrowserServer, login) -> None:
    """The chip opens with the keyboard and a persona can be chosen with it."""
    login("persona_data_steward")
    trigger = page.locator('[data-testid="persona-trigger"]')
    trigger.focus()
    page.keyboard.press("Enter")
    assert page.locator('[data-testid="demo-switch"]').is_visible()
    # The first choice follows the chip in the tab order.
    page.keyboard.press("Tab")
    first = page.locator('[data-demo-persona="persona_applicant"]')
    assert first.evaluate("element => element === document.activeElement")
    # And it can be chosen with the keyboard.
    page.locator('[data-demo-persona="persona_permit_reviewer"]').focus()
    page.keyboard.press("Enter")
    page.wait_for_url(f"{server.base_url}/queue*")
    assert "Permit Reviewer" in page.locator('[data-testid="acting-persona"]').inner_text()


@pytest.mark.parametrize(("width", "height"), ((1280, 800), (390, 844)))
def test_the_menu_fits_the_screen(
    page, server: BrowserServer, login, width: int, height: int
) -> None:
    """The chip and its menu fit a desktop and a phone."""
    login("persona_data_steward")
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{server.base_url}/queue", wait_until="load")
    page.locator('[data-testid="persona-trigger"]').click()
    assert_no_horizontal_overflow(page)
    menu = page.locator('[data-testid="demo-switch"]')
    box = menu.bounding_box()
    assert box is not None
    assert box["x"] >= 0 and box["x"] + box["width"] <= width, box
    assert box["y"] >= 0 and box["y"] + box["height"] <= height, box
    for index in range(5):
        assert menu.locator("[data-demo-persona]").nth(index).is_visible()


def test_the_bottom_left_overlay_is_gone(page, server: BrowserServer, login) -> None:
    """The staff frame carries no floating switcher any more."""
    login("persona_data_steward")
    assert page.locator(".demo-switch").count() == 0
    assert page.locator(".demo-corner-bottom-left").count() == 0
    assert page.locator("text=Open the City website home").count() == 0


def test_the_city_header_carries_the_menu_for_the_applicant(
    page, server: BrowserServer, login
) -> None:
    """On the City site the applicant sees the Demo controls chip and menu."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/city/", wait_until="load")
    trigger = page.locator('.city-header [data-testid="persona-trigger"]')
    assert trigger.is_visible()
    assert "Demo controls" in trigger.get_attribute("aria-label")
    trigger.click()
    menu = page.locator('.city-header [data-testid="demo-switch"]')
    assert menu.is_visible()
    assert menu.locator("[data-demo-persona]").count() == 5
    assert page.locator('.city-header [data-testid="sign-out"]').is_visible()
    assert page.locator(".demo-switch").count() == 0


@pytest.mark.parametrize(("actor_id", "home"), PERSONAS)
def test_each_city_menu_item_switches_and_lands_on_its_home(
    page, server: BrowserServer, login, actor_id: str, home: str
) -> None:
    """From the City site, every persona item switches and opens that home."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/city/", wait_until="load")
    page.locator('.city-header [data-testid="persona-trigger"]').click()
    page.locator(f'.city-header [data-demo-persona="{actor_id}"]').click()
    page.wait_for_url(f"{server.base_url}{home}*")
    assert page.url.split("?")[0].endswith(home), page.url
    assert page.evaluate("() => fetch('/api/session').then(r => r.json()).then(j => j.actor_id)") == actor_id


def test_the_city_menu_works_with_the_keyboard(page, server: BrowserServer, login) -> None:
    """The City chip opens with the keyboard and a persona is chosen with it."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/city/", wait_until="load")
    page.locator('.city-header [data-testid="persona-trigger"]').focus()
    page.keyboard.press("Enter")
    assert page.locator('.city-header [data-testid="demo-switch"]').is_visible()
    page.keyboard.press("Tab")
    first = page.locator('.city-header [data-demo-persona="persona_applicant"]')
    assert first.evaluate("element => element === document.activeElement")
    page.locator('.city-header [data-demo-persona="persona_permit_reviewer"]').focus()
    page.keyboard.press("Enter")
    page.wait_for_url(f"{server.base_url}/queue*")
    assert "Permit Reviewer" in page.locator('[data-testid="acting-persona"]').inner_text()


@pytest.mark.parametrize(("width", "height"), ((1280, 800), (390, 844)))
def test_the_city_menu_fits_the_screen(
    page, server: BrowserServer, login, width: int, height: int
) -> None:
    """The City chip and its menu fit a desktop and a 390 px phone."""
    login("persona_applicant")
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{server.base_url}/city/", wait_until="load")
    assert_no_horizontal_overflow(page)
    page.locator('.city-header [data-testid="persona-trigger"]').click()
    assert_no_horizontal_overflow(page)
    menu = page.locator('.city-header [data-testid="demo-switch"]')
    box = menu.bounding_box()
    assert box is not None
    assert box["x"] >= 0 and box["x"] + box["width"] <= width, box
    assert box["y"] >= 0 and box["y"] + box["height"] <= height, box
    for index in range(5):
        assert menu.locator("[data-demo-persona]").nth(index).is_visible()


def test_a_signed_out_city_visitor_sees_no_menu(page, server: BrowserServer) -> None:
    """Without a session the City header offers no persona menu."""
    page.goto(f"{server.base_url}/city/", wait_until="load")
    assert page.locator('[data-testid="persona-trigger"]').count() == 0
    assert page.locator("[data-demo-persona]").count() == 0
