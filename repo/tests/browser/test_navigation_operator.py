"""The browser navigation tests of the agent operator lane.

The agent operator lane adds its navigation browser tests here; ``test_navigation.py``
is frozen.  Empty until the lane adds a test.
"""
# REQUIRES: UX-01

from __future__ import annotations

from conftest import assert_no_horizontal_overflow, assert_not_covered


def test_operator_navigation_has_four_visible_destinations_at_390(viewport_390, login) -> None:
    page = viewport_390
    login("persona_agent_operator")
    links = page.locator(".mobile-nav a")
    assert links.count() == 4
    assert [links.nth(index).get_attribute("href") for index in range(4)] == [
        "/agents", "/agent/intake", "/agent/adjudication", "/agents/runs",
    ]
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator(".mobile-nav"))
