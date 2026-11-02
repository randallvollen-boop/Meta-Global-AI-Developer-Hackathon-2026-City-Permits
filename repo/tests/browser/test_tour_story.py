"""The tour can fill the fence form, and it can name the issued permit.

Fill in the story's answers writes the form in the browser. It does not
submit. Check my application then passes for a 4 ft back yard fence. A 6 ft
fence in the front yard is a Must fix, because that is the published limit.

The permit card after Issue permit names the permit of this visit and links
the public search already filled with that number.
"""

from __future__ import annotations

from conftest import BrowserServer

PERMIT = "ACME-2026-000731"
ADDRESS = "12 Marrow Creek Road, ACME City"


def test_fill_then_check_passes_and_six_feet_in_front_must_be_fixed(
    page, server: BrowserServer, login
) -> None:
    """A 4 ft back yard fence has no Must fix. 6 ft in the front yard does."""
    login("persona_applicant")
    page.evaluate(
        """() => sessionStorage.setItem("acme-tour", JSON.stringify({
            active: true, index: 3, playing: false, intervalMs: 0, path: "resident"
        }))"""
    )
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    page.wait_for_selector('[data-testid="tour-fill"]')
    page.locator('[data-testid="tour-fill"]').click()
    assert page.locator('[name="height_ft"]').input_value() == "4"
    assert page.locator('[name="location"]').input_value() == "side_rear"
    assert page.locator('[name="address_text"]').input_value() == "400 Lantern Row, ACME City"
    assert page.locator('[data-testid="certify"]').is_checked() is False
    page.evaluate(
        """() => {
            const panel = document.querySelector('[data-testid="tour-panel"]');
            if (panel) panel.style.pointerEvents = "none";
        }"""
    )
    page.locator('[data-testid="check-application"]').click()
    page.wait_for_selector('[data-testid="must-fix"]')
    must = page.locator('[data-testid="must-fix"]')
    assert must.locator('[data-testid="presubmit-item"]').count() == 0
    assert "None." in must.inner_text()
    page.locator('[name="location"]').select_option("front")
    page.locator('[name="height_ft"]').fill("6")
    page.locator('[data-testid="check-application"]').click()
    page.wait_for_selector('[data-testid="must-fix"] [data-testid="presubmit-item"]')
    assert page.locator('[data-testid="must-fix"] [data-testid="presubmit-item"]').count() >= 1


def test_the_permit_card_links_the_search_for_this_permit(
    page, server: BrowserServer, login
) -> None:
    """The card after issuance names this permit and opens its public search."""
    page.context.add_cookies(
        [
            {
                "name": "acme_judge_case",
                "value": "app_d07",
                "url": server.base_url,
                "httpOnly": True,
                "sameSite": "Lax",
            }
        ]
    )
    login("persona_permit_reviewer")
    page.evaluate(
        """() => sessionStorage.setItem("acme-tour", JSON.stringify({
            active: true, index: 5, playing: false, intervalMs: 0, path: "cafe"
        }))"""
    )
    page.goto(f"{server.base_url}/permits/app_d07", wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="tour-permit-card"]:not([hidden])')
    issued = page.locator('[data-testid="tour-permit-card"]').inner_text()
    assert PERMIT in issued
    assert ADDRESS in issued
    assert "ACME-P-1002" in issued
    assert "Approved" in issued
    assert "none recorded" in issued

    page.evaluate(
        """() => sessionStorage.setItem("acme-tour", JSON.stringify({
            active: true, index: 6, playing: false, intervalMs: 0, path: "cafe"
        }))"""
    )
    page.goto(f"{server.base_url}/city/community", wait_until="networkidle")
    page.wait_for_selector('[data-testid="tour-permit-search"]')
    link = page.locator('[data-testid="tour-permit-search"]')
    assert link.inner_text().strip() == "Search for my permit"
    href = link.get_attribute("href") or ""
    assert f"q={PERMIT}" in href
    caption = page.locator('[data-testid="tour-caption"]').inner_text()
    assert f"Search for permit {PERMIT} or {ADDRESS}." in caption
    page.goto(f"{server.base_url}{href}", wait_until="domcontentloaded")
    assert page.locator('[data-testid="community-q"]').input_value() == PERMIT
    page.locator('[data-testid="community-search"]').click()
    page.wait_for_selector('[data-testid="community-results"]')
    assert PERMIT in page.locator('[data-testid="community-results"]').inner_text()
