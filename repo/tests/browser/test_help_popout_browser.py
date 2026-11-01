"""The help window of the applicant, in the browser.

The header of every applicant page carries one launcher.  It opens the
assistant in a small window of its own, so the fields and the files the
applicant typed in the form stay exactly as they were.  Without JavaScript
the launcher is an ordinary link, and the window opens in a tab of its own.
"""
# REQUIRES: UX-02, UX-03, PER-04, SEC-03

from __future__ import annotations

from conftest import BrowserServer

FENCE_QUESTION = "Do I need a permit for a 6 ft fence?"


def sign_in(context, server: BrowserServer, actor_id: str):
    """Return a signed-in page of a browser context."""
    page = context.new_page()
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator(f'button[data-persona="{actor_id}"]').click()
    page.wait_for_url(f"{server.base_url}/city/")
    return page


def test_the_launcher_opens_the_window_with_its_named_arguments(
    page, server: BrowserServer, login
) -> None:
    """The window is opened with the name and the size of the demonstration."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    page.evaluate(
        "() => {"
        " window.__opened = [];"
        " window.open = function (url, name, features) {"
        "   window.__opened.push([url, name, features]);"
        "   return null;"
        " };"
        "}"
    )
    page.locator('[data-testid="help-popout"]').click()
    opened = page.evaluate("window.__opened")
    assert opened == [
        [
            "/apply/help/panel?placement=popout",
            "acme-permit-help",
            "width=420,height=680,noopener",
        ]
    ], opened


def test_the_launcher_opens_a_window_that_answers(page, server: BrowserServer, login) -> None:
    """The window carries the panel, and the answer arrives in it."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    with page.expect_popup() as opened:
        page.locator('[data-testid="help-popout"]').click()
    window = opened.value
    window.wait_for_load_state("domcontentloaded")
    assert "/apply/help/panel?placement=popout" in window.url
    assert window.locator('[data-testid="help-panel"]').count() == 1
    window.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
    window.locator('[data-testid="help-submit"]').click()
    window.wait_for_selector('[data-testid="help-turn"]')
    assert window.locator('[data-testid="help-turn"]').count() == 1
    assert "ACME Code §14-306" in window.locator('[data-testid="help-panel"]').inner_text()


def test_the_window_works_without_javascript(browser, server: BrowserServer) -> None:
    """Without a script the launcher is an ordinary link."""
    context = browser.new_context(java_script_enabled=False)
    try:
        page = sign_in(context, server, "persona_applicant")
        page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
        with context.expect_page() as opened:
            page.locator('[data-testid="help-popout"]').click()
        window = opened.value
        window.wait_for_load_state("domcontentloaded")
        assert "/apply/help/panel" in window.url
        assert window.locator('[data-testid="help-panel"]').count() == 1
    finally:
        context.close()


def test_the_fields_of_the_form_survive_the_question(browser, server: BrowserServer) -> None:
    """The window is separate, so what the applicant typed stays in the form."""
    context = browser.new_context(java_script_enabled=False)
    try:
        page = sign_in(context, server, "persona_applicant")
        page.goto(f"{server.base_url}/apply/deck_fence", wait_until="domcontentloaded")
        page.locator("#f-applicant_name").fill("Demo Applicant")
        page.locator("#f-height_ft").fill("4")
        with context.expect_page() as opened:
            page.locator('[data-testid="help-popout"]').click()
        window = opened.value
        window.wait_for_load_state("domcontentloaded")
        window.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
        # Without a script the answer is served in the window itself.
        window.locator('[data-testid="help-submit"]').click()
        window.wait_for_selector('[data-testid="help-turn"]')
        assert window.locator('[data-testid="help-turn"]').count() == 1
        # The form the applicant typed in still holds what was typed.
        assert page.locator("#f-applicant_name").input_value() == "Demo Applicant"
        assert page.locator("#f-height_ft").input_value() == "4"
    finally:
        context.close()
