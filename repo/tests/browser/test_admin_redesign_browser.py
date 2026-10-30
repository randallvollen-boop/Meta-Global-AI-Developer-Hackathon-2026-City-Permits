"""The redesigned administration screens in a browser.

Every screen of the redesign has to fit a 390 pixel phone, the controls a
person needs must stay clear of the mobile navigation and the demo switch, and
the appearance section must keep the saved icons usable while it says plainly
that a generation is not available.
"""
# REQUIRES: UX-01, UX-02, AI-03
# The redesigned screens are checked at the size of a phone: no horizontal
# overflow, no covered control and no hidden action.

from __future__ import annotations

import pytest

from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

ADMINISTRATOR = "persona_city_administrator"

PERSONA_HOMES = (
    ("persona_applicant", "/city/", "Welcome to the City of Acme"),
    ("persona_data_steward", "/steward", "Data issues"),
    ("persona_permit_reviewer", "/queue", "Work queue"),
    ("persona_city_administrator", "/overview", "Planning overview"),
    ("persona_agent_operator", "/agents", "Agents"),
)


@pytest.mark.parametrize(("actor_id", "home", "heading"), PERSONA_HOMES)
def test_every_persona_opens_its_home_on_desktop_without_errors(
    page, server: BrowserServer, login, actor_id: str, home: str, heading: str
) -> None:
    """ADA-17: the five demo personas each reach an error-free desktop home."""
    login(actor_id)
    assert page.url.split("?", 1)[0].rstrip("/").endswith(home.rstrip("/")), page.url
    assert page.locator("main h1").inner_text().strip() == heading
    assert page.recorded_errors == []


def test_the_appearance_section_fits_a_phone_and_keeps_the_saved_icons(
    page, server: BrowserServer, login
) -> None:
    login(ADMINISTRATOR)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/admin?tab=appearance", wait_until="domcontentloaded")
    assert_no_horizontal_overflow(page)

    # Every permit type shows the icon the City uses and its own settings.
    assert page.locator('[data-testid="permit-type-icon-row"]').count() == 17
    assert page.locator('[data-testid="permit-type-current-icon"]').count() == 17
    # The saved icons of a type stay reachable.
    editor = page.locator('[data-testid="icon-editor"]').first
    editor.locator("summary").click()
    assert editor.locator('[data-testid="icon-save-form"]').count() == 1
    assert editor.locator('[data-testid="icon-thumb"]').count() >= 1
    assert_no_horizontal_overflow(page)

    # The generation is offered only when the deployment may make one, and the
    # screen says why when it may not.
    disabled = page.locator('[data-testid="icon-generate"][disabled]').count()
    notice = page.locator('[data-testid="icon-generation-unavailable"]')
    if notice.count() == 1:
        assert disabled == 17
        assert "Live Muse generation is off." in notice.inner_text()
    else:
        assert disabled == 0

    # Neither the mobile bar nor the demo switch covers the icons.
    assert_not_covered(page, page.locator(".demo-switch > summary"))
    assert_not_covered(page, page.locator('[data-testid="permit-type-current-icon"]').first)
    assert page.recorded_errors == []


def test_the_planning_overview_fits_a_phone_and_leads_with_attention(
    page, server: BrowserServer, login
) -> None:
    login(ADMINISTRATOR)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/overview", wait_until="domcontentloaded")
    assert_no_horizontal_overflow(page)

    for testid in (
        "overview-attention-count",
        "overview-changes-count",
        "overview-property-count",
        "overview-sources-count",
    ):
        assert page.locator(f'[data-testid="{testid}"]').is_visible(), testid

    # Attention comes before the versions that are not published.
    order = page.evaluate(
        "() => ['attention', 'changes', 'property', 'sources'].map("
        "(key) => document.querySelector(`[data-testid=overview-${key}-count]`)"
        ".getBoundingClientRect().top)"
    )
    assert order == sorted(order)

    # The property context still opens in the shared drawer on a phone.
    link = page.locator('[data-detail-kind="property-context"]').first
    link.scroll_into_view_if_needed()
    assert_not_covered(page, link)
    link.click()
    drawer = page.locator('[data-testid="ui-drawer"]')
    drawer.wait_for(state="visible")
    assert "Property context" in drawer.inner_text()
    page.keyboard.press("Escape")
    drawer.wait_for(state="hidden")

    assert_not_covered(page, page.locator(".demo-switch > summary"))
    assert page.recorded_errors == []
