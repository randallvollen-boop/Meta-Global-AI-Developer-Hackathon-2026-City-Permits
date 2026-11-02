"""The reviewer screens in a real browser: queue views, workspace tabs and fit."""
# REQUIRES: UX-01, UX-02, UX-03
# The reviewer filters the queue by view, switches workspace tabs, opens the
# technical-details drawer, and nothing scrolls sideways at 390 px.

from __future__ import annotations

from conftest import BrowserServer

CASE = "app_synth_001"


def no_sideways_scroll(page) -> bool:
    return page.evaluate(
        "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )


def test_queue_views_filter_and_fit_on_a_phone(page, server: BrowserServer, login) -> None:
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/queue?view=all", wait_until="domcontentloaded")
    views = page.locator('[data-testid="queue-view"]')
    assert views.count() >= 2
    total = page.locator('[data-testid="queue-item"]').count()
    page.locator('[data-testid="queue-view"][data-view="issued"]').click()
    page.wait_for_url("**focus=issued**")
    assert page.locator('[data-testid="queue-item"]').count() == 1
    assert total > 1
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(f"{server.base_url}/queue?view=all", wait_until="domcontentloaded")
    title = page.locator('[data-testid="queue-row-title"]').first
    assert title.is_visible()
    assert page.locator('[data-testid="queue-action"]').first.is_visible()
    assert page.recorded_errors == []


def test_workspace_tabs_switch_and_the_drawer_opens(page, server: BrowserServer, login) -> None:
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/{CASE}", wait_until="domcontentloaded")
    assert page.locator("#panel-review").is_visible()
    assert page.locator("#panel-documents").is_hidden()
    page.locator('#tab-documents').click()
    assert page.locator("#panel-documents").is_visible()
    assert page.locator("#panel-review").is_hidden()
    documents = page.locator('[data-testid="documents-section"]')
    assert documents.get_attribute("open") is None
    assert page.locator('[data-testid="document-table"]').is_hidden()
    documents.locator("summary").click()
    assert page.locator('[data-testid="document-table"]').is_visible()
    page.locator('#tab-review').click()
    assert page.locator('[data-testid="next-action"]').is_visible()
    # Run application checks lives on the Review tab. There is no side rail.
    assert page.locator("aside.rail").count() == 0
    assert page.locator('details[data-action-id="permit.evaluate"]').is_visible()
    page.locator('#tab-activity').click()
    assert page.locator('details[data-action-id="permit.evaluate"]').is_hidden()
    page.locator('[data-detail-kind="case-tech"]').first.click()
    page.locator("#ui-drawer").wait_for(state="visible")
    assert "app_synth_001" in page.locator("#ui-drawer").inner_text()
    page.keyboard.press("Escape")
    assert page.locator("#ui-drawer").is_hidden()
    assert page.recorded_errors == []


def test_the_workspace_fits_a_phone(page, server: BrowserServer, login) -> None:
    login("persona_permit_reviewer")
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(f"{server.base_url}/permits/{CASE}", wait_until="domcontentloaded")
    assert page.locator('[data-testid="case-header"]').is_visible()
    assert no_sideways_scroll(page)
    for tab in ("documents", "people", "activity"):
        page.locator(f"#tab-{tab}").click()
        assert no_sideways_scroll(page), tab
    assert page.recorded_errors == []
