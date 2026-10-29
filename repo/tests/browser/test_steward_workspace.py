"""The workspace of the Data Steward in a browser.

The queue reads its search and its filters from the address of the request.
On a desktop it is a table with its columns; on a phone it is one card per
task, and the bar of the phone keeps the four work screens and the demo
switcher reachable.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02, UX-04

from __future__ import annotations

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.session import SessionFactory, transaction


@pytest.fixture()
def cedarline(server: BrowserServer) -> list[str]:
    """Add the Cedarline proposals to the database of the browser server."""
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            return seed_cedarline(session)
    finally:
        factory.dispose()


def test_the_queue_with_the_filters_open_fits_a_phone(
    viewport_390, server: BrowserServer, login
) -> None:
    """The queue, the search and the open filters fit a 390 pixel screen."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    assert page.viewport_size == {"width": 390, "height": 844}
    filters = page.locator('[data-testid="queue-filters"]')
    assert filters.count() == 1
    filters.locator("summary").click()
    assert filters.locator("select").count() == 2
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert_not_covered(page, page.locator('[data-testid="queue-filter-submit"]'))
    assert page.recorded_errors == []


def test_the_search_reads_the_address_and_the_queue_answers(
    page, server: BrowserServer, login
) -> None:
    """The search travels in the address, and the queue answers with the rows."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="domcontentloaded")
    search = page.locator('[data-testid="queue-search"]')
    assert search.count() == 1
    search.locator('input[name="q"]').fill("notarecord")
    search.locator('[data-testid="queue-search-submit"]').click()
    page.wait_for_url("**/steward?q=notarecord")
    assert page.locator('[data-testid="queue-empty"]').count() == 1
    assert page.locator("[data-issue-row]").count() == 0


def test_the_filters_keep_the_queue_readable_at_a_phone(
    viewport_390, server: BrowserServer, login
) -> None:
    """A filtered queue stays inside the screen and keeps its rows."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward?record_type=match", wait_until="load")
    filters = page.locator('[data-testid="queue-filters"]')
    assert filters.locator("summary").inner_text().strip().lower() == "more filters"
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_queue_reads_as_one_card_per_task_on_a_phone(
    viewport_390, server: BrowserServer, login, cedarline
) -> None:
    """At 390 pixels the table becomes one card per task, and every card fits."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    assert not page.locator('[data-testid="issue-table"] thead').is_visible()
    rows = page.locator("[data-issue-row]")
    assert rows.count() == 3
    assert rows.first.evaluate("element => getComputedStyle(element).display") == "block"
    for index in range(rows.count()):
        box = rows.nth(index).bounding_box()
        assert box is not None
        assert box["x"] >= 0, box
        assert box["x"] + box["width"] <= 390, box
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_queue_keeps_its_columns_on_a_desktop(
    page, server: BrowserServer, login, cedarline
) -> None:
    """On a desktop the queue keeps its columns, its reason and its action."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    assert page.locator('[data-testid="issue-table"] thead').is_visible()
    assert page.locator("[data-issue-row]").first.evaluate(
        "element => getComputedStyle(element).display"
    ) == "table-row"
    assert page.locator('[data-testid="issue-reason"]').count() == 3
    assert page.locator('[data-testid="issue-action"]').count() == 3
    assert page.locator('[data-testid="issue-reference"]').count() == 3
    assert page.recorded_errors == []


def test_the_bar_and_the_demo_switch_stay_reachable(
    viewport_390, server: BrowserServer, login, cedarline
) -> None:
    """The four work screens and the demo switcher stay reachable on a phone."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    entries = page.locator(".mobile-nav > a")
    assert entries.count() == 4
    assert page.locator('[data-testid="demo-switch"]').is_visible()
    assert_not_covered(page, page.locator('[data-testid="demo-switch"] > summary'))
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_case_opens_with_a_compact_summary_of_the_task(
    page, server: BrowserServer, login, cedarline
) -> None:
    """The case names the task, the record, the source, the status and the next step."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    page.locator("[data-issue-row]", has_text="ERP-BL-00413").locator(
        '[data-testid="issue-link"]'
    ).click()
    page.wait_for_selector('[data-testid="case-summary"]')
    summary = page.locator('[data-testid="case-summary"]')
    summary_text = summary.inner_text()
    assert summary.locator("h1").inner_text().strip() == "Check the business identity"
    assert "Cedarline Coffee Works" in summary_text
    assert "ERP-BL-00413" in summary_text
    assert summary.locator('[data-testid="case-status"]').inner_text().strip() == "Needs review"
    assert summary.locator('[data-testid="case-summary-source"]').inner_text().strip()
    assert summary.locator('[data-testid="case-summary-next"]').inner_text().strip()
    # The summary reads before the comparison and repeats none of its text.
    page_html = page.content()
    assert page_html.index("case-summary") < page_html.index('data-question="3"')
    assert "Source record ERP-BL-00413" not in summary_text
    assert "Check the business identity" not in page_html.split('data-question="1"')[1]
    assert page.recorded_errors == []


def test_the_case_summary_fits_a_phone(
    viewport_390, server: BrowserServer, login, cedarline
) -> None:
    """The summary of the case and the questions below it fit a 390 pixel screen."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    page.locator("[data-issue-row]", has_text="ERP-BL-00413").locator(
        '[data-testid="issue-link"]'
    ).click()
    page.wait_for_selector('[data-testid="case-summary"]')
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert_not_covered(page, page.locator('[data-testid="case-summary-next"]'))
    assert page.locator('[data-testid="case-q6"]').count() == 1
    assert page.recorded_errors == []


def test_the_comparison_fits_a_phone(
    viewport_390, server: BrowserServer, login, cedarline
) -> None:
    """The comparison of the case fits a 390 pixel screen, with every value labelled."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    page.locator("[data-issue-row]", has_text="ERP-BL-00413").locator(
        '[data-testid="issue-link"]'
    ).click()
    page.wait_for_selector('[data-testid="compare-table"]')
    table = page.locator('[data-testid="compare-table"]').first
    # On a phone the table becomes one card per field, and the column heads
    # become the labels of the values.
    assert not table.locator("thead").is_visible()
    assert table.locator('[data-label="Source record"]').count() >= 1
    assert table.locator('[data-label="Master record"]').count() >= 1
    for row in table.locator("tbody tr").all():
        box = row.bounding_box()
        assert box is not None
        assert box["x"] >= 0, box
        assert box["x"] + box["width"] <= 390, box
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []
