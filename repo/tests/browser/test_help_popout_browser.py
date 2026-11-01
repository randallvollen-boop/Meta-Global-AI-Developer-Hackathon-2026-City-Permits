"""The assistant panel of the applicant, in the browser.

The launcher at the corner of the page opens the panel over the page: the
page stays where it is, nothing navigates, and the fields and the files the
applicant typed stay exactly as they were.  The panel is closed with its own
button or with the Escape key, and the keyboard stays inside it while it is
open.  Without JavaScript the launcher is an ordinary link and the panel
opens on a page of its own.
"""
# REQUIRES: UX-02, UX-03, PER-04, SEC-03

from __future__ import annotations

from conftest import BrowserServer, assert_not_covered

FENCE_QUESTION = "Do I need a permit for a 6 ft fence?"


def sign_in(context, server: BrowserServer, actor_id: str):
    """Return a signed-in page of a browser context."""
    page = context.new_page()
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator(f'button[data-persona="{actor_id}"]').click()
    page.wait_for_url(f"{server.base_url}/city/")
    return page


def open_panel(page, launcher: str = '[data-testid="help-chat-launcher"]') -> None:
    """Open the panel of the page and wait for the assistant to arrive."""
    page.locator(launcher).click()
    page.wait_for_selector('[data-testid=help-panel]')
    page.wait_for_selector('[data-testid=help-question]')


def test_the_launcher_opens_the_panel_over_the_page(
    page, server: BrowserServer, login
) -> None:
    """The panel slides up over the page, and the page stays where it is."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    page.evaluate("() => { window.__still_here = 'kept'; }")
    url = page.url

    open_panel(page)

    assert page.locator('[data-testid="help-panel-sheet"]').is_visible()
    assert page.locator('[data-testid="help-panel"]').count() == 1
    assert page.locator('[data-testid="help-form"]').count() == 1
    # Nothing navigated and nothing reloaded the page.
    assert page.url == url
    assert page.evaluate("window.__still_here") == "kept"
    assert page.recorded_errors == []


def test_the_header_launcher_opens_the_same_panel(
    page, server: BrowserServer, login
) -> None:
    """The launcher of the header opens the same panel over the page."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    open_panel(page, '[data-testid="help-ask"]')
    assert page.locator('[data-testid="help-panel"]').count() == 1
    assert page.url.endswith("/apply")
    # The focus comes back to the launcher that opened it.
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement.getAttribute('data-testid')") == (
        "help-ask"
    )


def test_the_help_of_the_menu_opens_the_same_panel(
    page, server: BrowserServer, login
) -> None:
    """The Help of the menu opens the same panel over the page."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    open_panel(page, '[data-testid="nav-help"]')
    assert page.locator('[data-testid="help-panel"]').count() == 1
    assert page.url.endswith("/apply")
    assert page.recorded_errors == []


def test_the_launcher_sits_at_the_corner_of_the_page(
    page, server: BrowserServer, login
) -> None:
    """The chat button sits at the corner of the page, on the page itself."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    launcher = page.locator('[data-testid="help-chat-launcher"]')
    assert launcher.is_visible()
    box = launcher.bounding_box()
    assert box["x"] + box["width"] == 1280 - 16, box
    assert box["y"] + box["height"] == 900 - 16, box
    assert_not_covered(page, launcher)
    assert page.recorded_errors == []


def test_the_panel_answers_the_question_in_place(
    page, server: BrowserServer, login
) -> None:
    """The answer arrives in the panel, and the page does not move."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    page.evaluate("() => { window.__still_here = 'kept'; }")
    url = page.url

    open_panel(page)
    page.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
    page.locator('[data-testid="help-submit"]').click()
    page.wait_for_selector('[data-testid="help-turn"]')

    assert page.locator('[data-testid="help-turn"]').count() == 1
    body = page.locator('[data-testid="help-panel"]').inner_text()
    assert "ACME Code §14-306" in body
    # The page was not reloaded to show the answer.  The address carries the
    # conversation, so a reload opens the panel on the same talk.
    assert page.url.split("?")[0] == url.split("?")[0]
    assert page.evaluate("window.__still_here") == "kept"
    assert page.recorded_errors == []


def test_the_fields_of_the_form_survive_the_question(
    page, server: BrowserServer, login
) -> None:
    """What the applicant typed in the form stays in the form."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="domcontentloaded")
    page.locator("#f-applicant_name").fill("Demo Applicant")
    page.locator("#f-height_ft").fill("4")

    open_panel(page)
    page.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
    page.locator('[data-testid="help-submit"]').click()
    page.wait_for_selector('[data-testid="help-turn"]')

    assert page.locator("#f-applicant_name").input_value() == "Demo Applicant"
    assert page.locator("#f-height_ft").input_value() == "4"


def test_the_close_button_closes_the_panel_and_gives_the_focus_back(
    page, server: BrowserServer, login
) -> None:
    """The panel is closed with its own button, and the focus comes back."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    open_panel(page)

    page.locator('[data-testid="help-panel-close"]').click()

    assert not page.locator('[data-testid="help-panel-sheet"]').is_visible()
    assert page.evaluate("document.activeElement.getAttribute('data-testid')") == (
        "help-chat-launcher"
    )
    assert page.recorded_errors == []


def test_the_escape_key_closes_the_panel(
    page, server: BrowserServer, login
) -> None:
    """The Escape key closes the panel, and the focus comes back."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    open_panel(page)

    page.keyboard.press("Escape")

    assert not page.locator('[data-testid="help-panel-sheet"]').is_visible()
    assert page.evaluate("document.activeElement.getAttribute('data-testid')") == (
        "help-chat-launcher"
    )
    assert page.recorded_errors == []


def test_the_keyboard_stays_inside_the_open_panel(
    page, server: BrowserServer, login
) -> None:
    """The panel is a dialog: the keyboard cannot leave it while it is open."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    open_panel(page)

    for _ in range(30):
        page.keyboard.press("Tab")
        inside = page.evaluate(
            "() => document.querySelector('[data-testid=help-panel-sheet]')"
            ".contains(document.activeElement)"
        )
        assert inside is True

    # And the panel can be closed with the keyboard alone.
    page.keyboard.press("Escape")
    assert not page.locator('[data-testid="help-panel-sheet"]').is_visible()


def test_the_panel_is_a_sheet_of_the_whole_width_on_a_phone(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """On a phone the panel covers the width of the screen."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    launcher = page.locator('[data-testid="help-chat-launcher"]')
    assert launcher.is_visible()
    assert_not_covered(page, launcher)
    open_panel(page)
    box = page.locator('[data-testid="help-panel-sheet"]').bounding_box()
    assert box["width"] == 390, box
    assert box["x"] == 0, box
    assert page.recorded_errors == []


def test_the_panel_works_without_javascript(browser, server: BrowserServer) -> None:
    """Without a script the launcher is an ordinary link."""
    context = browser.new_context(java_script_enabled=False)
    try:
        page = sign_in(context, server, "persona_applicant")
        page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
        page.locator('[data-testid="help-chat-launcher"]').click()
        page.wait_for_load_state("domcontentloaded")
        assert "/apply/help/panel" in page.url
        assert page.locator('[data-testid="help-panel"]').count() == 1
        # The answer of the panel still arrives, on the page of its own.
        page.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
        page.locator('[data-testid="help-submit"]').click()
        page.wait_for_selector('[data-testid="help-turn"]')
        assert page.locator('[data-testid="help-turn"]').count() == 1
    finally:
        context.close()
