"""The browser navigation of the Data Steward.

The steward works in four places, and the bar of a phone holds those four
plus More tools.  The demo switch lands the steward on its own work queue.
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

#: The four screens of the side navigation, in the order they are listed.
PRIMARY = ("steward", "masters", "source_records", "activity")


def test_the_demo_switch_lands_the_steward_on_its_work_queue(
    page, server: BrowserServer
) -> None:
    """The steward lands on /steward, and that page answers."""
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator('button[data-persona="persona_data_steward"]').click()
    page.wait_for_url(f"{server.base_url}/steward")
    response = page.goto(f"{server.base_url}/steward", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 200
    assert page.locator("main h1").count() == 1


def test_the_side_navigation_holds_four_entries_and_more_tools(
    page, server: BrowserServer, login
) -> None:
    """The side navigation lists the four work screens and a More tools group."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="domcontentloaded")
    primary = page.locator(".side .app-nav > ul > li > a")
    assert primary.count() == len(PRIMARY)
    keys = [primary.nth(index).get_attribute("data-screen-key") for index in range(primary.count())]
    assert keys == list(PRIMARY)
    more = page.locator('.side [data-testid="nav-more"]')
    assert more.count() == 1
    assert more.locator("a").count() >= 1
    assert "more tools" in more.inner_text().lower()


def test_the_phone_bar_holds_four_entries_and_more_tools(
    viewport_390, server: BrowserServer, login
) -> None:
    """At 390 pixels the bar holds the four work screens and More tools."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    assert page.viewport_size == {"width": 390, "height": 844}
    entries = page.locator(".mobile-nav > a")
    assert entries.count() == len(PRIMARY)
    more = page.locator('.mobile-nav [data-testid="nav-more-mobile"]')
    assert more.is_visible()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert_not_covered(page, more.locator("summary"))
    assert page.recorded_errors == []
