"""The admin-b screens in the browser: the phone fit of every screen.

The harness of the lane is shared by its slices.  It opens a screen as the
City Administrator at 390 by 844 pixels, checks that the page does not scroll
sideways, that the mobile navigation and the demo switcher do not cover the
controls of the screen and that the browser reports no error.

The first slice of the lane adds the harness and the guard that keeps the new
stylesheet away from the screens of the other lanes.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04

from __future__ import annotations

from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

#: The screens of the other lanes, with the address that opens each of them.
OTHER_SCREENS = (
    ("persona_applicant", "/city/"),
    ("persona_data_steward", "/queue"),
    ("persona_permit_reviewer", "/queue"),
    ("persona_city_administrator", "/queue"),
)

#: The staff screens, which carry the shared "Last action" region.
STAFF_SCREENS = (
    ("persona_data_steward", "/queue"),
    ("persona_permit_reviewer", "/queue"),
    ("persona_city_administrator", "/queue"),
)


def open_screen(page, server: BrowserServer, path: str) -> None:
    """Open one screen of the demonstration server."""
    page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")


def fits_a_phone(page) -> None:
    """Check that the page fits a phone and that its heading is reachable."""
    assert_no_horizontal_overflow(page)
    heading = page.locator("main h1").first
    if heading.count():
        assert_not_covered(page, heading)


def test_the_admin_b_stylesheet_does_not_reach_the_other_screens(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """The scoped stylesheet may not change a screen the lane does not own."""
    for actor_id, path in OTHER_SCREENS:
        login(actor_id)
        open_screen(page, server, path)
        assert_no_horizontal_overflow(page)
        assert page.locator(".admin-b").count() == 0, path
    assert page.recorded_errors == []


def test_the_other_screens_keep_their_feedback_region(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """The shared "Last action" region survives the new stylesheet."""
    for actor_id, path in STAFF_SCREENS:
        login(actor_id)
        open_screen(page, server, path)
        assert page.locator('[data-testid="feedback"]').count() == 1, path
        assert page.locator('[data-testid="feedback-message"]').count() == 1, path
    assert page.recorded_errors == []
