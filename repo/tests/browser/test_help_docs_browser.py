"""The in-app tutorial in a real browser: open it from Help and follow one link."""
# REQUIRES: UX-01
# The Help link opens the hub, the tutorial opens from it, and a "Go to this
# screen" link lands on the screen its step names.

from __future__ import annotations

from conftest import BrowserServer


def test_help_link_opens_the_tutorial_and_a_step_link_lands_on_its_screen(
    page, server: BrowserServer, login
) -> None:
    login("persona_permit_reviewer")
    page.locator('[data-testid="help-link"]').click()
    page.wait_for_url(f"{server.base_url}/help")
    page.locator('[data-testid="help-card-tutorial"]').click()
    page.wait_for_url(f"{server.base_url}/help/tutorial")
    assert page.locator('[data-testid="tutorial-section"]').count() == 5
    section = page.locator('[data-testid="tutorial-section"][data-persona-id="persona_permit_reviewer"]')
    assert section.locator("h2").inner_text().endswith("Permit Reviewer")
    section.locator('[data-testid="tutorial-go"]').first.click()
    page.wait_for_url(f"{server.base_url}/queue")
    assert page.locator("h1").first.inner_text() == "Work queue"
    assert page.recorded_errors == []


def test_the_architecture_page_runs_no_script_in_its_frame(page, server: BrowserServer, login) -> None:
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/help/technical/architecture", wait_until="domcontentloaded")
    frame = page.frame_locator('[data-testid="document-frame"]')
    frame.locator("body").wait_for()
    # The page's own theme button is a script feature; in the sandbox it cannot reach the app origin.
    assert page.evaluate(
        "() => { try { return document.querySelector('iframe').contentDocument === null; }"
        " catch (error) { return true; } }"
    )
    assert page.locator('[data-testid="document-frame"]').get_attribute("sandbox") == ""
