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

from datetime import UTC, datetime

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.models import audit
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


#: A record identifier that is long enough to widen a table on a phone.
LONG_RECORD = "PER-AP-0003-with-a-very-long-identifier-0123456789-abcdefghij"


@pytest.fixture()
def long_record(server: BrowserServer) -> str:
    """Record one activity event whose record identifier is very long."""
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                audit.AuditEvent(
                    id="audit_activity_long_record",
                    correlation_id="correlation_activity",
                    occurred_at=datetime(2026, 10, 20, 9, 30, tzinfo=UTC),
                    actor_id="persona_data_steward",
                    action="registry.crosswalk.propose",
                    target_type="source_record",
                    target_id=LONG_RECORD,
                    reason="a long identifier wraps instead of widening the screen",
                    outcome="accepted",
                )
            )
    finally:
        factory.dispose()
    return LONG_RECORD


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
    assert page.locator("[data-issue-row]").count() == 4
    counts = page.locator('[data-testid="issue-filter-count"]').all_inner_texts()
    assert counts == ["4", "0", "0", "0"]
    # The row of the record: the task is the link, the reference is the text
    # under the source.
    page.locator("[data-issue-row]", has_text="ERP-BL-00413").locator(
        '[data-testid="issue-link"]'
    ).click()
    page.wait_for_selector('[data-question="6"]')
    assert page.locator('[data-testid="candidate"]').count() == 2
    # The note on the similar name sits behind the disclosure of the evidence.
    page.locator('[data-testid="case-q4-details"] > summary').click()
    assert page.locator('[data-testid="similar-note"]').is_visible()
    previews = page.locator('[data-testid="action-preview"]')
    assert previews.count() >= 4
    for width in (1280, 390):
        page.set_viewport_size({"width": width, "height": 900})
        assert overflow(page) <= 1, ("case", width, overflow(page))
    # The preview and the guard text are visible next to each action, not hidden.
    assert previews.first.is_visible()
    assert page.recorded_errors == []


def test_the_task_shows_what_was_submitted_and_opens_the_application(
    page, server: BrowserServer, login, cedarline
) -> None:
    """The panel reads side by side, and the link opens the application."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="domcontentloaded")
    page.locator("[data-issue-row]", has_text="ERP-BL-00413").locator(
        '[data-testid="issue-link"]'
    ).click()
    page.wait_for_selector('[data-testid="submitted-panel"]')
    rows = page.locator('[data-testid="submitted-row"]')
    assert rows.count() > 0, "the panel lists the fields in question"
    # Every row says in words how the two sides differ.
    for index in range(rows.count()):
        difference = rows.nth(index).locator('[data-testid="submitted-difference"]')
        assert difference.count() == 1
        assert difference.inner_text().strip() in {
            "The same.",
            "They differ.",
            "Only the record holds this value.",
            "Only the submission holds this value.",
            "Neither side holds a value.",
        }
    # The link opens the application the issue came from.
    link = page.locator('[data-testid="case-application-link"]')
    assert link.count() == 1
    link.click()
    page.wait_for_selector('[data-testid="application-number"]')
    assert page.locator('[data-testid="application-field-list"]').count() == 1
    assert page.locator('[data-testid="application-documents"]').count() == 1
    # The application page is read only: it carries no action at all.
    assert page.locator("[data-action-id]").count() == 0
    for width in (1280, 390):
        page.set_viewport_size({"width": width, "height": 900})
        assert overflow(page) <= 1, ("application", width, overflow(page))
    assert page.recorded_errors == []


def test_a_decision_made_in_the_browser_shows_on_the_case(page, server: BrowserServer, login, cedarline, submit_action) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="domcontentloaded")
    page.locator("[data-issue-row]", has_text="PER-AP-0003").locator(
        '[data-testid="issue-link"]'
    ).click()
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
        "/queue/intake",
        "/queue/early-resolution",
        "/masters?detail=record:party_cedarline",
        "/masters?tab=registrations&detail=credential:cred_contractor_halcyon",
    ]
    for path in paths:
        response = page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert response is not None and response.status in (200, 404), path
        assert overflow(page) <= 1, (path, width, overflow(page))
    assert page.recorded_errors == []


def test_the_activity_keeps_its_columns_on_a_desktop(
    page, server: BrowserServer, login, cedarline
) -> None:
    """On a desktop the activity list keeps its columns: the change, the note, the actor and the result."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/activity", wait_until="load")
    table = page.locator('[data-testid="activity-table"]')
    assert table.count() == 1
    assert table.locator("thead").is_visible()
    assert table.locator("thead th").all_inner_texts() == [
        "Change and record",
        "Note",
        "Actor and time",
        "Result",
    ]
    row = page.locator('[data-testid="activity-row"]').first
    assert row.evaluate("element => getComputedStyle(element).display") == "table-row"
    assert row.locator('[data-testid="activity-action"]').inner_text().strip()
    assert row.locator('[data-testid="activity-target"]').inner_text().strip()
    assert row.locator('[data-testid="activity-result"]').inner_text().strip() == "Recorded"
    assert page.recorded_errors == []


def test_the_activity_reads_as_one_card_per_event_on_a_phone(
    viewport_390, server: BrowserServer, login, cedarline
) -> None:
    """At 390 pixels the activity list becomes one card per event, and every card fits."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/activity", wait_until="load")
    assert page.viewport_size == {"width": 390, "height": 844}
    table = page.locator('[data-testid="activity-table"]')
    assert table.count() == 1
    assert not table.locator("thead").is_visible()
    rows = page.locator('[data-testid="activity-row"]')
    assert rows.count() >= 1
    for index in range(rows.count()):
        box = rows.nth(index).bounding_box()
        assert box is not None
        assert box["x"] >= 0, box
        assert box["x"] + box["width"] <= 390, box
    card = rows.first
    assert card.locator('[data-testid="activity-action"]').inner_text().strip()
    assert card.locator('[data-testid="activity-target"]').inner_text().strip()
    assert card.locator('[data-testid="activity-result"]').inner_text().strip() == "Recorded"
    # The card reads in one order: the action, the result and then the note.
    action = card.locator('[data-testid="activity-action"]').bounding_box()
    result = card.locator('[data-testid="activity-result"]').bounding_box()
    note = card.locator('[data-testid="activity-note"]').bounding_box()
    assert action is not None and result is not None and note is not None
    assert action["y"] < result["y"] < note["y"]
    # The record of the event is named on the card.
    label = card.locator('[data-testid="activity-target"]').evaluate(
        "element => getComputedStyle(element, '::before').content"
    )
    assert "Record" in label
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert_not_covered(page, page.locator('[data-testid="activity-row"]').first)
    assert page.recorded_errors == []


def test_a_long_record_identifier_fits_a_phone(
    viewport_390, server: BrowserServer, login, long_record
) -> None:
    """A long record identifier wraps inside the card instead of widening it."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/activity", wait_until="load")
    row = page.locator('[data-testid="activity-row"]', has_text=long_record).first
    assert row.count() == 1
    box = row.bounding_box()
    assert box is not None
    assert box["x"] >= 0, box
    assert box["x"] + box["width"] <= 390, box
    assert_no_horizontal_overflow(page)
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
