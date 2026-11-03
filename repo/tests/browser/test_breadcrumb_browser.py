"""The breadcrumb of a page is one line, whatever the width of the window.

The trail of the help pages is one row of crumbs.  A long last crumb
truncates with an ellipsis instead of wrapping to a second row, and the page
never grows wider than the window.
"""
# REQUIRES: UX-01

from __future__ import annotations

from conftest import BrowserServer, assert_no_horizontal_overflow

#: A guide with a long title: the crumb that has to truncate.
LONG_PAGE = "/help/how-to/track-an-application-and-answer-a-request"


def trail_heights(page) -> dict[str, float]:
    """Return the height of the trail and the height of one line of it."""
    return page.evaluate(
        """() => {
          const nav = document.querySelector('[aria-label="Breadcrumb"]');
          const list = nav.querySelector('ol');
          const items = [...list.querySelectorAll('li')];
          return {
            trail: list.getBoundingClientRect().height,
            line: items[0].getBoundingClientRect().height,
            last: items[items.length - 1].getBoundingClientRect().height,
          };
        }"""
    )


def assert_one_line(page, path: str) -> None:
    """Assert that the page carries one breadcrumb and that it is one row."""
    crumbs = page.evaluate(
        """() => document.querySelectorAll('[aria-label="Breadcrumb"], [class*="crumb"]').length"""
    )
    assert crumbs == 1, (path, crumbs)
    heights = trail_heights(page)
    assert heights["trail"] <= heights["line"] * 1.5, (path, heights)
    assert heights["last"] <= heights["line"] * 1.5, (path, heights)


def test_the_breadcrumb_of_a_help_page_is_one_line(page, server: BrowserServer, login) -> None:
    """The trail of the help pages is one row at the width of a small window."""
    login("persona_applicant")
    page.set_viewport_size({"width": 900, "height": 900})
    for path in ("/help/tutorial", LONG_PAGE):
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert_one_line(page, path)
        assert_no_horizontal_overflow(page)


def test_the_breadcrumb_of_a_help_page_truncates_at_the_width_of_a_phone(
    page, server: BrowserServer, login
) -> None:
    """At the width of a phone the trail truncates and the page keeps its width."""
    login("persona_applicant")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}{LONG_PAGE}", wait_until="domcontentloaded")
    assert_one_line(page, LONG_PAGE)
    truncated = page.locator('[aria-label="Breadcrumb"] li').last.evaluate(
        "element => element.scrollWidth > element.clientWidth + 1"
    )
    assert truncated, "the long title should truncate with an ellipsis"
    assert_no_horizontal_overflow(page)


def test_a_long_title_truncates_in_the_staff_frame(page, server: BrowserServer, login) -> None:
    """The staff frame is narrower, so the long crumb truncates there."""
    login("persona_permit_reviewer")
    page.set_viewport_size({"width": 900, "height": 900})
    page.goto(f"{server.base_url}{LONG_PAGE}", wait_until="domcontentloaded")
    assert_one_line(page, LONG_PAGE)
    truncated = page.locator('[aria-label="Breadcrumb"] li').last.evaluate(
        "element => element.scrollWidth > element.clientWidth + 1"
    )
    assert truncated, "the long title should truncate with an ellipsis"
    assert_no_horizontal_overflow(page)
