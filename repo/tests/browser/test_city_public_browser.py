"""The disclosures of the public pages and of the walkthrough open.

Every "More details" of the slimming is a control a person presses, so each
one is clicked here: the disclosure opens and the detail it holds appears.
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

from conftest import BrowserServer

#: The card link of one public record.
CARD_LINK = '[data-testid="community-result-table"] .community-card-link'


def test_the_recently_submitted_list_opens(page, server: BrowserServer) -> None:
    """The recently submitted permits sit behind a disclosure and open."""
    page.goto(f"{server.base_url}/city/community", wait_until="networkidle")
    disclosure = page.locator('[data-testid="community-recent"]')
    assert disclosure.count() == 1
    card = disclosure.locator(".community-card-link").first
    assert not card.is_visible()
    disclosure.locator("summary").click()
    assert card.is_visible()
    assert page.recorded_errors == []


def test_the_record_page_opens_its_more_details(page, server: BrowserServer) -> None:
    """The conditions and the property details of a record open on request."""
    page.goto(f"{server.base_url}/city/community?q=Acme", wait_until="networkidle")
    href = page.locator(CARD_LINK).first.get_attribute("href")
    page.goto(f"{server.base_url}{href}", wait_until="networkidle")
    detail = page.locator("details.community-record-more")
    assert detail.count() == 1
    district = detail.locator('[data-field="district"]')
    assert not district.is_visible()
    detail.locator("summary").click()
    assert district.is_visible()
    assert page.recorded_errors == []


def test_the_service_page_opens_its_contact_disclosure(page, server: BrowserServer) -> None:
    """The related information of a service page opens on request."""
    page.goto(f"{server.base_url}/city/parks", wait_until="networkidle")
    disclosure = page.locator("details.city-aside")
    assert disclosure.count() == 1
    assert not disclosure.locator("p").first.is_visible()
    disclosure.locator("summary").click()
    assert disclosure.locator("p").first.is_visible()
    assert page.recorded_errors == []


def test_the_permits_entry_opens_what_you_need(page, server: BrowserServer) -> None:
    """What you need for a permit opens on request."""
    page.goto(f"{server.base_url}/city/permits", wait_until="networkidle")
    disclosure = page.locator('[data-testid="permits-need"] details')
    assert disclosure.count() == 1
    item = disclosure.locator('[data-testid="need-item"]').first
    assert not item.is_visible()
    disclosure.locator("summary").click()
    assert item.is_visible()
    assert page.recorded_errors == []


def test_the_walkthrough_step_opens_its_more_details(page, server: BrowserServer) -> None:
    """The look-for line of a walkthrough step opens on request."""
    page.goto(f"{server.base_url}/walkthrough", wait_until="networkidle")
    step = page.locator('[data-testid="walkthrough-step"]').first
    disclosure = step.locator("details.guide-more")
    assert disclosure.count() == 1
    assert not disclosure.locator("p").first.is_visible()
    disclosure.locator("summary").click()
    assert disclosure.locator("p").first.is_visible()
    assert page.recorded_errors == []
