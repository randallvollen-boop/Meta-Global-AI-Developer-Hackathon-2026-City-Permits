"""A status pill is one crisp line on every screen.

The City Administrator reads the state of a version in a column of pills:
"Published" in the rules register, the state of a version on the planning
overview, the result of a check in the operations screens.  The word of a
state must never break over two lines, and the pill must have the same box
on every screen.

The browser measures the line boxes of the text itself: a range over the
text of a pill reports one rectangle for one line and two for a word that
broke.
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow

#: The administrator who reads the screens.
ADMINISTRATOR = "persona_city_administrator"

#: The screens that carry a state in a column, and the pill inside them.
SCREENS = (
    ("/rules", '[data-testid="rule-row"] td[data-label="Status"] .badge'),
    ("/rules?tab=rules&view=drafts", '[data-testid="rule-row"] td[data-label="Status"] .badge'),
    ("/overview", '[data-testid="overview-changes-row"] .badge'),
    ("/ops/checks", '[data-testid="check-row"] .ops-badge'),
)

#: Measure the line boxes of the text of one pill.
MEASURE = """(element) => {
  const range = document.createRange();
  range.selectNodeContents(element);
  const rects = Array.from(range.getClientRects())
    .filter((rect) => rect.width > 0 && rect.height > 0);
  const style = getComputedStyle(element);
  return {
    lines: rects.length,
    lineBox: rects.length ? rects[0].height : 0,
    whiteSpace: style.whiteSpace,
    height: element.getBoundingClientRect().height,
    fontSize: style.fontSize,
    text: element.textContent.trim(),
  };
}"""


def _open(page, server: BrowserServer, path: str) -> None:
    """Open one screen of the administrator, with its states on the page."""
    page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
    if path == "/overview":
        # The versions that wait to be published sit behind a disclosure.
        page.locator('[data-testid="overview-changes-more"] summary').click()
    if path == "/ops/checks" and page.locator('[data-testid="check-row"]').count() == 0:
        # The checks have not run yet: run them, then read the screen again.
        with page.expect_response(
            lambda response: "/ui/actions/ops.checks.run" in response.url
        ):
            page.locator('[data-testid="checks-run"]').click()
        page.reload(wait_until="domcontentloaded")


@pytest.mark.parametrize("viewport", [(1280, 900), (390, 844)])
def test_every_state_pill_is_one_line(
    page, server: BrowserServer, login, viewport: tuple[int, int]
) -> None:
    """No state of the City breaks over two lines."""
    login(ADMINISTRATOR)
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    seen = 0
    for path, selector in SCREENS:
        _open(page, server, path)
        pills = page.locator(selector)
        for index in range(pills.count()):
            measured = pills.nth(index).evaluate(MEASURE)
            assert measured["lines"] == 1, (path, measured)
            assert measured["whiteSpace"] == "nowrap", (path, measured)
            assert measured["text"], (path, measured)
            # The pill is one line of text plus its own compact padding.
            assert measured["lineBox"] > 0, (path, measured)
            assert measured["height"] <= measured["lineBox"] + 12, (path, measured)
            seen += 1
    assert seen > 0, "no state pill was found"


@pytest.mark.parametrize("viewport", [(1280, 900), (390, 844)])
def test_the_state_pills_of_the_screens_have_one_box(
    page, server: BrowserServer, login, viewport: tuple[int, int]
) -> None:
    """The pill of a state has the same height and size on every screen."""
    login(ADMINISTRATOR)
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    boxes = set()
    for path, selector in SCREENS:
        _open(page, server, path)
        pills = page.locator(selector)
        for index in range(pills.count()):
            measured = pills.nth(index).evaluate(MEASURE)
            boxes.add((measured["height"], measured["fontSize"]))
    assert boxes, "no state pill was found"
    assert len(boxes) == 1, boxes


def test_the_rules_screen_keeps_its_state_column_readable(
    page, server: BrowserServer, login
) -> None:
    """The state column of the rules register is as wide as the pill."""
    login(ADMINISTRATOR)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{server.base_url}/rules", wait_until="domcontentloaded")
    rows = page.locator('[data-testid="rule-row"]')
    assert rows.count() > 0, "the register holds a version"
    for index in range(rows.count()):
        cell = rows.nth(index).locator('td[data-label="Status"]')
        pill = cell.locator(".badge")
        assert pill.count() == 1
        # The pill lies inside its cell: the column fits the word.
        assert pill.evaluate(
            """(element) => {
              const pill = element.getBoundingClientRect();
              const cell = element.closest('td').getBoundingClientRect();
              return pill.right <= cell.right + 1 && pill.left >= cell.left - 1;
            }"""
        )


def test_the_state_pills_do_not_push_the_page_sideways(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """On a phone the table scrolls inside its own region."""
    login(ADMINISTRATOR)
    for path, _ in SCREENS:
        _open(page, server, path)
        assert_no_horizontal_overflow(page)
        # The region that holds the table scrolls; the pill never breaks.
        region = page.locator('[data-testid="rule-table"], [data-testid="overview-changes-table"]')
        if region.count() == 0:
            continue
        assert region.first.evaluate(
            "element => { const style = getComputedStyle(element.parentElement);"
            " return ['auto', 'scroll'].includes(style.overflowX); }"
        ), path
