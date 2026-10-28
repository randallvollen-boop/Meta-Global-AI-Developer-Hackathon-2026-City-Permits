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
from conftest import BrowserServer

ADMINISTRATOR = "persona_city_administrator"


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
    ):
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 1, (path, overflow)
    assert page.recorded_errors == []
