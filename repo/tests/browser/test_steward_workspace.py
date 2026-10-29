"""The workspace of the Data Steward in a browser.

The queue reads its search and its filters from the address of the request,
and the queue with the filters open fits a phone.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02, UX-04

from __future__ import annotations

from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered


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
