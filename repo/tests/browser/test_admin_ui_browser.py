"""The City Administrator screens in a real browser.

The planning overview is the Administrator's home.  The property context opens
in the shared side flyout, the rules and fee register opens the selected
version with its diff, and the reconciliation screen keeps the receipt
register apart from the selected assessment.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04, GOV-04, SEC-01
# The Administrator screens render, open the shared flyout, show the diff of
# the selected version and stay inside a 390 pixel viewport.

from __future__ import annotations

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

from acme_city.ui import admin_tabs
# The router loads the navigation plugins of the lanes, so the tabs other
# lanes registered are known here as well.
from acme_city.ui.router import router as ui_router  # noqa: F401

ADMINISTRATOR = "persona_city_administrator"

#: The five sections of the administration screen.
SECTIONS = ("permit-types", "appearance", "users", "reason-codes", "log")


def test_the_administrator_lands_on_the_planning_overview(
    page, server: BrowserServer, login
) -> None:
    login(ADMINISTRATOR)
    assert page.url.rstrip("/").endswith("/overview"), page.url
    heading = page.locator("h1").first.inner_text()
    assert heading == "Planning overview"
    assert page.locator('[data-testid="overview-cards"]').count() == 1
    assert page.recorded_errors == []


def test_the_overview_counts_come_with_their_definition(
    page, server: BrowserServer, login
) -> None:
    login(ADMINISTRATOR)
    card = page.locator('[data-testid="overview-attention-count"]')
    assert card.count() == 1
    text = card.inner_text().strip()
    assert text.isdigit(), text
    definition = page.locator('[data-testid="overview-attention-count"]').locator(
        "xpath=ancestor::section[1]"
    )
    assert "Sample applications" in definition.inner_text()


def test_the_property_context_opens_in_the_shared_flyout(
    page, server: BrowserServer, login
) -> None:
    login(ADMINISTRATOR)
    drawer = page.locator("#ui-drawer")
    assert drawer.is_hidden()
    link = page.locator('[data-detail-kind="property-context"]').first
    link.click()
    drawer.wait_for(state="visible")
    assert "detail=property-context:" in page.url
    text = drawer.inner_text()
    assert "ACME-P-1001" in text
    assert "400 Lantern Row Unit 2" in text
    page.keyboard.press("Escape")
    assert drawer.is_hidden()


def test_the_rules_register_opens_the_selected_version_with_its_diff(
    page, server: BrowserServer, login
) -> None:
    login(ADMINISTRATOR)
    page.goto(f"{server.base_url}/rules?tab=rules&view=drafts", wait_until="domcontentloaded")
    action = page.locator('[data-testid="rule-next-action"]').first
    assert action.inner_text().strip() == "Submit for review"
    action.click()
    page.wait_for_selector('[data-testid="selected-version"]')
    selected = page.locator('[data-testid="selected-version"]')
    text = selected.inner_text()
    assert "250000" in text
    assert "300000" in text
    assert "overlap" in text.lower()
    assert "initial submission time" in text
    assert page.recorded_errors == []


def test_the_demo_moment_opens_the_draft_and_takes_the_next_step(
    page, server: BrowserServer, login, submit_action
) -> None:
    """The Administrator opens the draft from the overview and acts on it."""
    login(ADMINISTRATOR)
    # The draft is reachable from the overview.
    page.goto(f"{server.base_url}/overview", wait_until="domcontentloaded")
    row = page.locator('[data-testid="overview-changes-row"]').first
    assert "CT-2@2" in row.inner_text()
    row.locator("a").first.click()
    page.wait_for_selector('[data-testid="selected-version"]')
    selected = page.locator('[data-testid="selected-version"]')
    text = selected.inner_text()
    assert "CT-2@2" in text
    assert "250000" in text
    assert "300000" in text
    # The next authorized step of a draft is to submit it for review.
    message = submit_action(
        "rule.submit", {"reason": "a fictional demonstration step"}
    )
    assert "in_review" in message
    page.reload(wait_until="domcontentloaded")
    assert page.locator('[data-testid="selected-version"]').count() == 1
    assert "awaiting approval" in page.locator(
        '[data-testid="selected-version"]'
    ).inner_text()
    # The recorded result is reported in the feedback region.
    assert "in_review" in page.locator('[data-testid="feedback-message"]').inner_text()
    assert page.recorded_errors == []


def test_the_reconciliation_screen_keeps_the_receipt_register_apart(
    page, server: BrowserServer, login
) -> None:
    login(ADMINISTRATOR)
    page.goto(f"{server.base_url}/reconciliation", wait_until="domcontentloaded")
    assert page.locator('[data-testid="assessment-table"]').count() == 1
    assert page.locator('[data-testid="payment-table"]').count() == 0
    page.locator('[data-testid="reconciliation-tab"][data-tab="receipts"]').click()
    page.wait_for_selector('[data-testid="payment-table"]')
    assert page.locator('[data-testid="assessment-table"]').count() == 0
    receipts = page.locator('[data-testid="payment-row"]')
    assert receipts.count() > 1


def test_the_selected_assessment_shows_its_receipts(
    page, server: BrowserServer, login
) -> None:
    login(ADMINISTRATOR)
    page.goto(f"{server.base_url}/reconciliation", wait_until="domcontentloaded")
    page.locator('[data-testid="assessment-view-details"]').first.click()
    page.wait_for_selector('[data-testid="selected-assessment"]')
    selected = page.locator('[data-testid="selected-assessment"]')
    assert "SYN-APP-007" in selected.inner_text()
    assert selected.locator('[data-testid="assessment-receipt-row"]').count() >= 1


@pytest.mark.parametrize("viewport", [(1280, 900), (390, 844)])
def test_the_administrator_screens_do_not_overflow(
    page, server: BrowserServer, login, viewport
) -> None:
    login(ADMINISTRATOR)
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    for path in (
        "/overview",
        "/rules?tab=rules&view=drafts",
        "/governance?tab=sources",
        "/reconciliation?tab=assessments",
        "/admin?tab=appearance",
        "/admin?tab=permit-types",
    ):
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 1, (path, overflow)
    assert page.recorded_errors == []


# ------------------------------------------------------- the section navigation


def test_the_sections_are_ordinary_links(page, server: BrowserServer, login) -> None:
    login(ADMINISTRATOR)
    page.goto(f"{server.base_url}/admin", wait_until="domcontentloaded")
    # The navigation is a row of links, not a tab widget.
    assert page.locator('[role="tablist"]').count() == 0
    assert page.locator('[role="tab"]').count() == 0
    tabs = page.locator('[data-testid="admin-tab"]')
    # The row holds the five sections of the screen and the tabs the lanes
    # registered with admin_tabs.register_admin_tab.
    assert tabs.count() == len(admin_tabs.ADMIN_TABS)
    for section in SECTIONS:
        assert page.locator(f'[data-testid="admin-tab"][data-tab="{section}"]').count() == 1
    # The section that is open is the current page.
    current = page.locator('[data-testid="admin-tab"][aria-current="page"]')
    assert current.count() == 1
    assert current.get_attribute("data-tab") == "permit-types"
    # Only the open section is on the page.
    assert page.locator('[data-testid="admin-section"]').count() == 1


def test_a_section_opens_the_section_it_names(page, server: BrowserServer, login) -> None:
    login(ADMINISTRATOR)
    page.goto(f"{server.base_url}/admin", wait_until="domcontentloaded")
    page.locator('[data-testid="admin-tab"][data-tab="reason-codes"]').click()
    page.wait_for_url("**/admin?tab=reason-codes")
    assert page.locator('[data-testid="admin-section"][data-section="reason-codes"]').count() == 1
    assert page.locator('[data-testid="admin-section"][data-section="permit-types"]').count() == 0
    current = page.locator('[data-testid="admin-tab"][aria-current="page"]')
    assert current.get_attribute("data-tab") == "reason-codes"
    assert page.recorded_errors == []


@pytest.mark.parametrize("section", SECTIONS)
def test_every_section_fits_a_phone(page, server: BrowserServer, login, section: str) -> None:
    login(ADMINISTRATOR)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/admin?tab={section}", wait_until="domcontentloaded")
    assert_no_horizontal_overflow(page)
    row = page.locator("nav.adm-tabs")
    box = row.bounding_box()
    assert box is not None
    assert box["x"] >= 0 and box["x"] + box["width"] <= 390, box
    # Neither the mobile bar nor the demo switch covers the navigation.
    assert_not_covered(page, page.locator('[data-testid="persona-trigger"]'))
    assert_not_covered(page, page.locator('[data-testid="admin-tab"][aria-current="page"]'))
    assert page.recorded_errors == []


def test_the_permit_type_register_fits_a_phone_and_opens_its_settings(
    page, server: BrowserServer, login
) -> None:
    login(ADMINISTRATOR)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/admin?tab=permit-types", wait_until="domcontentloaded")
    assert_no_horizontal_overflow(page)
    rows = page.locator('[data-testid="admin-permit-type-row"]')
    assert rows.count() == 17
    # The settings of a type open in place, with the governed document forms.
    settings = rows.first.locator('[data-testid="admin-permit-type-settings"]')
    assert settings.count() == 1
    settings.locator("summary").click()
    assert settings.locator('[data-testid="admin-document-toggle"]').count() > 0
    assert "Changes apply to new applications." in settings.inner_text()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator('[data-testid="persona-trigger"]'))
    assert page.recorded_errors == []


@pytest.mark.parametrize("section", ("users", "reason-codes"))
def test_users_and_reason_codes_fit_a_phone(page, server: BrowserServer, login, section: str) -> None:
    login(ADMINISTRATOR)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/admin?tab={section}", wait_until="domcontentloaded")
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator('[data-testid="persona-trigger"]'))
    if section == "users":
        people = page.locator('[data-testid="admin-person-row"]')
        personas_before = people.locator('[data-testid="admin-demo-persona"]').count()
        from acme_city.ui.view_models import PERSONA_PROFILES

        assert personas_before == len(PERSONA_PROFILES)
        assert personas_before == people.count()
        page.locator('[data-testid="admin-service-identities-disclosure"] > summary').click()
        assert people.locator('[data-testid="admin-demo-persona"]').count() == personas_before
    else:
        page.locator(".adm-retire-confirm > summary").first.click()
        assert "Existing records keep this code." in page.locator(".adm-retire-confirm").first.inner_text()
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


def test_the_administrator_creates_sample_data(page, server: BrowserServer, login) -> None:
    """The button creates the sample cases the demonstration needs."""
    login(ADMINISTRATOR)
    page.goto(f"{server.base_url}/admin?tab=sample-data", wait_until="domcontentloaded")
    assert page.locator('[data-testid="admin-sample-data-submit"]').is_visible()
    page.fill("#sample-data-count", "3")
    with page.expect_response(
        lambda response: "/ui/actions/intake.generate" in response.url
        and response.request.method == "POST"
    ) as answered:
        page.click("[data-testid='admin-sample-data-submit']")
    payload = answered.value.json()
    assert payload["status"] == "accepted", payload
    assert len(payload["affected"]) == 3, payload
    assert page.recorded_errors == []
