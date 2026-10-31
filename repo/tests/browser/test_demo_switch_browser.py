"""The demo switcher in the top bar of the staff frame, at 390 by 844."""
# REQUIRES: UX-01

from __future__ import annotations

from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

PERSONAS = (
    "persona_applicant",
    "persona_agent_operator",
    "persona_data_steward",
    "persona_permit_reviewer",
    "persona_city_administrator",
)


def test_open_switch_fits_five_choices_at_390(
    viewport_390, server: BrowserServer, login
) -> None:
    page = viewport_390
    login("persona_data_steward")
    # Changed deliberately (persona switcher, S4): the switcher is the chip in
    # the top bar, and its menu opens under the header.
    page.locator('[data-testid="persona-trigger"]').click()
    buttons = page.locator("[data-demo-persona]")
    assert buttons.count() == 5
    assert [buttons.nth(i).get_attribute("data-demo-persona") for i in range(5)] == list(PERSONAS)
    for i in range(5):
        assert buttons.nth(i).is_visible()
    assert_no_horizontal_overflow(page)
    # The open menu sits above the bottom bar of the staff app.
    nav = page.locator(".mobile-nav")
    assert nav.is_visible()
    panel = page.locator('[data-testid="demo-switch"]').bounding_box()
    bar = nav.bounding_box()
    assert panel is not None and bar is not None
    assert panel["y"] + panel["height"] <= bar["y"] + 1
    # The mobile bar covers neither the chip nor the choices.
    assert_not_covered(page, page.locator('[data-testid="persona-trigger"]'))
    assert_not_covered(page, buttons.nth(0))
    assert_not_covered(page, buttons.nth(4))
