"""The browser walkthrough of the eight screens.

The walkthrough visits every screen, checks that nothing overflows at 390
pixels, that the keyboard reaches the controls and that no page reports an
error.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04, GOV-04, SEC-01
# The eight screens render, stay inside a 390 pixel viewport, keep their
# labels and their status region, and reach the keyboard controls.

from __future__ import annotations

from conftest import BrowserServer

#: The eight screens of the demonstration and the path of their detail.
SCREENS = (
    ("/queue", "Work queue"),
    ("/applicants", "Applicants"),
    ("/masters", "Properties, businesses and contractors"),
    ("/permits/app_synth_001", "Permit workspace"),
    ("/steward", "Steward review"),
    ("/rules-fees", "Rules and fees"),
    ("/reconciliation", "Reconciliation"),
    ("/governance", "Governance and sources"),
)


def test_the_eight_screens_render_without_a_page_error(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    for path, title in SCREENS:
        response = page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert response is not None
        assert response.status == 200, path
        assert page.title().startswith(title.split(":")[0]), path
    assert page.recorded_errors == []


def test_the_navigation_holds_the_eight_screens(page, server: BrowserServer, login) -> None:
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/queue", wait_until="domcontentloaded")
    items = page.locator(".side .app-nav a")
    assert items.count() == 8
    keys = [items.nth(index).get_attribute("data-screen-key") for index in range(8)]
    assert keys == [
        "queue",
        "applicants",
        "masters",
        "permit",
        "steward",
        "rules",
        "reconciliation",
        "governance",
    ]


def test_no_screen_overflows_at_390_pixels(page, server: BrowserServer, login) -> None:
    login("persona_city_administrator")
    page.set_viewport_size({"width": 390, "height": 844})
    for path, _title in SCREENS:
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 1, (path, overflow)


def test_no_screen_overflows_on_a_desktop_viewport(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    page.set_viewport_size({"width": 1280, "height": 900})
    for path, _title in SCREENS:
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 1, (path, overflow)


def test_the_keyboard_reaches_the_skip_link_and_the_controls(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/queue", wait_until="domcontentloaded")
    page.keyboard.press("Tab")
    focused = page.evaluate("() => document.activeElement.className")
    assert "skip-link" in focused
    outline = page.evaluate(
        "() => { const style = window.getComputedStyle(document.activeElement);"
        " return style.outlineStyle + ' ' + style.outlineWidth; }"
    )
    assert "none" not in outline
    for _ in range(12):
        page.keyboard.press("Tab")
    tag = page.evaluate("() => document.activeElement.tagName")
    assert tag in {"A", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "SUMMARY"}


def test_every_control_of_a_screen_is_labelled(page, server: BrowserServer, login) -> None:
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/queue", wait_until="domcontentloaded")
    unlabelled = page.evaluate(
        """() => {
            const controls = Array.from(
                document.querySelectorAll('input, select, textarea')
            ).filter((element) => element.type !== 'hidden');
            return controls
                .filter((element) => {
                    if (element.getAttribute('aria-label')) { return false; }
                    if (element.id && document.querySelector(`label[for="${element.id}"]`)) {
                        return false;
                    }
                    return !element.closest('label');
                })
                .map((element) => element.outerHTML.slice(0, 80));
        }"""
    )
    assert unlabelled == []


def test_the_feedback_region_announces_the_outcome(
    page, server: BrowserServer, login
) -> None:
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    region = page.locator('[data-testid="feedback"]')
    assert region.count() == 1
    assert region.get_attribute("role") == "status"
    assert region.get_attribute("aria-live") == "polite"


def test_the_evidence_and_history_panels_stay_present(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    for path, _title in SCREENS:
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert page.locator('[data-testid="evidence-panel"]').count() == 1, path


def test_the_history_panel_stays_present_on_the_record_screens(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    for path in ("/permits/app_synth_001", "/steward", "/applicants/party_cedarline"):
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert page.locator('[data-testid="history-panel"]').count() == 1, path


def test_the_banner_states_that_the_data_is_fictional(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/queue", wait_until="domcontentloaded")
    banner = page.locator('[data-testid="demo-banner"]').inner_text()
    assert "Fictional ACME City demonstration" in banner
    assert "Westerville" not in banner
