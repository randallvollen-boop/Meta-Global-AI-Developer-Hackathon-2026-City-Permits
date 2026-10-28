"""The Data Steward screens in a real browser: tabs, the record drawer, Data issues and a focused case.

Checked at 1280 and at 390 pixels.  The Cedarline story is added to the
browser fixture's database through the demo module, exactly as the
``steward-demo`` prepare mode does; the reset itself never holds it.
"""
# REQUIRES: UX-01, UX-02, UX-03, SEC-01, MDM-02
# The master-record tabs switch collections, a record opens in the shared
# drawer with Overview, Sources and History, a focused case answers its six
# questions, and none of it overflows a 390 pixel screen.

from __future__ import annotations

import pytest
from conftest import BrowserServer

from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.session import SessionFactory, transaction


@pytest.fixture()
def cedarline(server: BrowserServer) -> list[str]:
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            return seed_cedarline(session)
    finally:
        factory.dispose()


def overflow(page) -> int:
    return page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")


def test_master_record_tabs_switch_one_collection_at_a_time(page, server: BrowserServer, login) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/masters", wait_until="domcontentloaded")
    assert page.locator('[data-testid="master-tab"]').count() == 4
    assert page.locator('[data-testid="applicant-table"]').is_visible()
    for tab, table in (
        ("properties", "property-table"),
        ("licenses", "business-table"),
        ("registrations", "contractor-table"),
        ("people", "applicant-table"),
    ):
        page.locator(f'[data-testid="master-tab"][data-tab="{tab}"]').click()
        page.wait_for_selector(f'[data-testid="{table}"]')
        assert page.locator('[data-testid="master-tab"][aria-current="page"]').get_attribute("data-tab") == tab
    assert page.recorded_errors == []


def test_a_record_opens_in_the_drawer_with_three_views(page, server: BrowserServer, login, cedarline) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/masters", wait_until="domcontentloaded")
    link = page.locator('[data-party-id="party_cedarline"] [data-testid="ui-detail-link"]').first
    link.focus()
    link.click()
    drawer = page.locator("#ui-drawer")
    drawer.wait_for(state="visible")
    assert "detail=record:party_cedarline" in page.url
    assert page.locator('[data-testid="ui-drawer-title"]').inner_text() == "Cedarline Coffee Roasters LLC"
    assert "Record status" in drawer.inner_text()
    # The page behind stays on screen, and the three views switch in place.
    assert page.locator('[data-testid="applicant-table"]').is_visible()
    page.locator('[data-testid="ui-drawer-tab"]', has_text="Sources").click()
    page.wait_for_function("() => document.querySelector('#ui-drawer').innerText.toLowerCase().includes('where each value came from')")
    assert "PER-AP-0003" in drawer.inner_text()
    page.locator('[data-testid="ui-drawer-tab"]', has_text="History").click()
    page.wait_for_function("() => document.querySelector('#ui-drawer').innerText.toLowerCase().includes('candidate links proposed')")
    # Escape closes it and focus returns to the record link.
    page.keyboard.press("Escape")
    drawer.wait_for(state="hidden")
    assert page.evaluate("() => document.activeElement.getAttribute('data-detail-id')") == "party_cedarline"
    assert page.recorded_errors == []


def test_data_issues_and_a_focused_case_at_both_widths(page, server: BrowserServer, login, cedarline) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="domcontentloaded")
    assert page.locator("[data-issue-row]").count() == 3
    counts = page.locator('[data-testid="issue-filter-count"]').all_inner_texts()
    assert counts == ["3", "0", "0", "0"]
    page.locator('[data-testid="issue-link"]', has_text="ERP-BL-00413").click()
    page.wait_for_selector('[data-question="6"]')
    assert page.locator('[data-testid="candidate"]').count() == 2
    assert page.locator('[data-testid="similar-note"]').is_visible()
    previews = page.locator('[data-testid="action-preview"]')
    assert previews.count() >= 4
    for width in (1280, 390):
        page.set_viewport_size({"width": width, "height": 900})
        assert overflow(page) <= 1, ("case", width, overflow(page))
    # The preview and the guard text are visible next to each action, not hidden.
    assert previews.first.is_visible()
    assert page.recorded_errors == []


def test_a_decision_made_in_the_browser_shows_on_the_case(page, server: BrowserServer, login, cedarline, submit_action) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="domcontentloaded")
    page.locator('[data-testid="issue-link"]', has_text="PER-AP-0003").click()
    page.wait_for_selector('[data-question="5"]')
    message = submit_action("registry.decide", {"reason": "the alias and the declared reference agree"})
    assert "Recorded the approve decision for PER-AP-0003" in message
    page.reload(wait_until="domcontentloaded")
    assert page.locator('[data-testid="case-confirmation"]').is_visible()
    assert "Linked to Cedarline Coffee Roasters LLC" in page.locator('[data-testid="case-result"]').inner_text()
    page.goto(f"{server.base_url}/steward?filter=resolved", wait_until="domcontentloaded")
    assert page.locator('[data-issue-row][data-link-status="approved"]').count() == 1
    assert page.recorded_errors == []


@pytest.mark.parametrize("width", [1280, 390])
def test_the_steward_screens_fit_the_screen(page, server: BrowserServer, login, cedarline, width: int) -> None:
    login("persona_data_steward")
    page.set_viewport_size({"width": width, "height": 900})
    paths = [
        "/masters",
        "/masters?tab=properties",
        "/masters?tab=licenses",
        "/masters?tab=registrations",
        "/masters/party_halcyon",
        "/masters/party_cedarline?view=sources",
        "/steward",
        "/source-records",
        "/activity",
        "/masters?detail=record:party_cedarline",
        "/masters?tab=registrations&detail=credential:cred_contractor_halcyon",
    ]
    for path in paths:
        response = page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert response is not None and response.status in (200, 404), path
        assert overflow(page) <= 1, (path, width, overflow(page))
    assert page.recorded_errors == []


def test_the_drawer_is_a_full_screen_sheet_at_390(page, server: BrowserServer, login, cedarline) -> None:
    login("persona_data_steward")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/masters?detail=record:party_cedarline", wait_until="domcontentloaded")
    box = page.locator("#ui-drawer").bounding_box()
    assert box is not None and box["width"] >= 388
    assert page.locator('[data-testid="ui-drawer-title"]').inner_text() == "Cedarline Coffee Roasters LLC"


def test_muted_text_stays_readable_in_the_dark_theme(page, server: BrowserServer, login, cedarline) -> None:
    login("persona_data_steward")
    page.emulate_media(color_scheme="dark")
    contrast = """
    () => {
      const parse = (value) => value.match(/[\\d.]+/g).slice(0, 3).map(Number);
      const lum = ([r, g, b]) => {
        const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
      };
      const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
      const background = parse(getComputedStyle(document.body).backgroundColor);
      return ['.page-head .sub', '.source-summary', '.data-table .muted'].map((selector) => {
        const element = document.querySelector(selector);
        return element ? [selector, ratio(parse(getComputedStyle(element).color), background)] : [selector, 21];
      });
    }
    """
    for path in ("/masters?tab=licenses", "/steward", "/source-records"):
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        for selector, value in page.evaluate(contrast):
            assert value >= 4.5, (path, selector, value)
