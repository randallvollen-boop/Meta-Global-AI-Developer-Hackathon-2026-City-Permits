"""The demo switcher at 390 by 844 with the panel open."""
# REQUIRES: UX-01

from __future__ import annotations

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

PERSONAS = (
    "persona_applicant",
    "persona_data_steward",
    "persona_permit_reviewer",
    "persona_city_administrator",
    "persona_agent_operator",
)


@pytest.mark.parametrize("actor_id", ["persona_data_steward", "persona_applicant"])
def test_open_switch_fits_five_choices_at_390(
    viewport_390, server: BrowserServer, login, actor_id: str
) -> None:
    page = viewport_390
    login(actor_id)
    page.locator(".demo-switch > summary").click()
    buttons = page.locator("[data-demo-persona]")
    assert buttons.count() == 5
    assert [buttons.nth(i).get_attribute("data-demo-persona") for i in range(5)] == list(PERSONAS)
    for i in range(5):
        assert buttons.nth(i).is_visible()
    assert_no_horizontal_overflow(page)
    # The open panel sits above the bottom bar of the staff app.
    nav = page.locator(".mobile-nav")
    if actor_id == "persona_data_steward":
        assert nav.is_visible()
    if nav.count() and nav.is_visible():
        panel = page.locator(".demo-switch-panel").bounding_box()
        bar = nav.bounding_box()
        assert panel is not None and bar is not None
        assert panel["y"] + panel["height"] <= bar["y"] + 1
        # The mobile bar covers neither the open button nor the choices.
        assert_not_covered(page, page.locator(".demo-switch > summary"))
        assert_not_covered(page, buttons.nth(0))
        assert_not_covered(page, buttons.nth(4))
