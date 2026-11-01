"""The slimmed operations, insight and rules screens, pressed in the browser.

Every control of these screens is pressed here: the filters of the city view
and the what-if it opens, the lookup and the request filter of support, the
tabs and the register of the rules, the clear of the audit filters and the
add and retire of a reason code.
"""
# REQUIRES: UX-01, UX-02, UX-03

from __future__ import annotations

import pytest

from conftest import BrowserServer, assert_no_horizontal_overflow


@pytest.fixture(autouse=True)
def patient_browser(page):
    """Give the page time to answer when the whole suite runs on one machine."""
    page.set_default_timeout(60_000)
    return page


def test_the_city_view_applies_its_filters_and_opens_a_quick_view(
    page, server: BrowserServer, login
) -> None:
    """Step 8: choose a permit type, press Apply, and use a quick view."""
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/insight/city", wait_until="domcontentloaded")
    key = page.locator('[data-testid="filter-type"] option:not([value=""])').first
    value = key.get_attribute("value")
    page.locator('[data-testid="filter-type"]').select_option(value)
    page.locator('[data-testid="filter-apply"]').click()
    page.wait_for_url(f"**/insight/city?type={value}**")
    assert page.locator('[data-testid="insight-filter-summary"]').count() == 1
    assert page.locator('[data-testid="district-table"]').count() == 1

    # The quick views sit behind More details and still work when opened.
    quick = page.locator('[data-testid="insight-quick-views"]')
    assert not quick.locator('[data-testid="insight-quick-links"]').is_visible()
    quick.locator("summary").click()
    page.locator('[data-testid="quick-restaurants-bars"]').click()
    page.wait_for_url("**/insight/city?category=**")
    assert page.locator('[data-testid="district-table"]').count() == 1

    # Clear filters takes the page back to the whole view.
    page.locator('[data-testid="filter-clear"]').click()
    page.wait_for_url(f"{server.base_url}/insight/city")
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


def test_the_city_view_opens_the_what_if_from_its_filters(
    page, server: BrowserServer, login
) -> None:
    """The link that starts a what-if carries the filters of the view."""
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/insight/city?type=deck_fence", wait_until="domcontentloaded")
    page.locator('[data-testid="start-whatif"]').click()
    page.wait_for_url("**/policy/scenarios**")
    assert page.locator('[data-testid="policy-starting"]').count() == 1
    assert "permit type deck_fence" in page.inner_text("body")
    assert page.recorded_errors == []


def test_support_looks_up_a_case_and_switches_the_request_filter(
    page, server: BrowserServer, login
) -> None:
    """The lookup button and the two request filters both work."""
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/ops/support", wait_until="domcontentloaded")
    page.locator('[data-testid="support-ref"]').fill("SYN-APP-005")
    page.locator('[data-testid="support-lookup-go"]').click()
    page.wait_for_selector('[data-testid="support-lookup-result"]')
    assert "SYN-APP-005" in page.locator('[data-testid="support-lookup-result"]').inner_text()

    page.locator('[data-testid="support-filter-answered"]').click()
    page.wait_for_url("**/ops/support?request_status=answered**")
    assert page.locator('[data-testid="support-requests"]').count() == 1
    assert page.recorded_errors == []


def test_the_rules_register_switches_tabs_and_opens_a_version(
    page, server: BrowserServer, login
) -> None:
    """The two tab rows and the next action of a version all work."""
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/rules?tab=rules&view=published", wait_until="domcontentloaded")
    page.locator('[data-testid="rules-tab"][data-tab="fees"]').click()
    page.wait_for_url("**/rules?tab=fees**")
    page.locator('[data-testid="rules-view"][data-view="history"]').click()
    page.wait_for_url("**/rules?tab=fees&view=history**")
    assert page.locator('[data-testid="rule-history-table"]').count() == 1

    page.goto(f"{server.base_url}/rules?tab=rules&view=published", wait_until="domcontentloaded")
    next_action = page.locator('[data-testid="rule-next-action"]').first
    next_action.click()
    page.wait_for_selector('[data-testid="selected-version"]')
    assert "What changed" in page.locator('[data-testid="selected-version"]').inner_text()
    assert page.recorded_errors == []


def test_the_audit_log_clears_its_filters(page, server: BrowserServer, login) -> None:
    """A filter that is applied can be cleared again."""
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/ops/audit", wait_until="domcontentloaded")
    page.locator('[data-testid="audit-filter-search"]').fill("permit")
    page.locator('[data-testid="audit-filter-apply"]').click()
    page.wait_for_url("**/ops/audit?**search=permit**")
    page.locator('[data-testid="audit-filter-clear"]').click()
    page.wait_for_url(f"{server.base_url}/ops/audit")
    assert page.locator('[data-testid="audit-filter-search"]').input_value() == ""
    assert page.recorded_errors == []


def test_the_administrator_adds_and_retires_a_reason_code(
    page, server: BrowserServer, login
) -> None:
    """The add form and the retire confirmation both work from the screen."""
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/admin?tab=reason-codes", wait_until="domcontentloaded")
    page.locator('[data-testid="admin-add-reason-code-disclosure"] > summary').click()
    page.locator("#rc-code").fill("DEMO_NOTE")
    page.locator("#rc-label").fill("Demo note")
    page.locator("#rc-description").fill("A code added from the screen")
    page.locator('[data-testid="admin-add-reason-code-submit"]').click()
    row = page.locator('[data-testid="admin-reason-code-row"][data-code="DEMO_NOTE"]')
    row.wait_for()
    assert "Demo note" in row.inner_text()

    row.locator(".adm-retire-confirm > summary").click()
    row.locator('[data-testid="admin-reason-code-retire"] button[type=submit]').click()
    page.wait_for_selector('[data-testid="admin-reason-code-row"][data-code="DEMO_NOTE"] .badge-superseded')
    assert "Retired" in row.inner_text()
    assert page.recorded_errors == []
