"""The applicant help panel in the browser.

The panel is offered on the chooser, on the application form and on the
tracker.  It works without JavaScript: the question is a form of its own and
the answer re-renders the page.  On the application form the answer opens in
a separate browsing context, so the fields and the files the applicant typed
stay exactly as they were.
"""
# REQUIRES: PORTAL-02, UX-02, UX-03, PER-04, SEC-03

from __future__ import annotations

from conftest import BrowserServer

#: The three places the panel is offered.
PLACEMENTS = (
    ("/apply", "chooser"),
    ("/apply/deck_fence", "form"),
    ("/apply/track?ref=SYN-APP-005", "track"),
)

FENCE_QUESTION = "Do I need a permit for a 6 ft fence?"


def sign_in(context, server: BrowserServer, actor_id: str):
    """Return a signed-in page of a browser context."""
    page = context.new_page()
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator(f'button[data-persona="{actor_id}"]').click()
    # The Applicant now lands on the City of Acme website; staff land on /queue.
    landing = "/city/" if actor_id == "persona_applicant" else "/queue"
    page.wait_for_url(f"{server.base_url}{landing}")
    return page


def test_the_panel_is_offered_on_the_three_portal_pages(
    page, server: BrowserServer, login
) -> None:
    login("persona_applicant")
    for path, placement in PLACEMENTS:
        response = page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert response is not None
        assert response.status == 200, path
        panel = page.locator('[data-testid="help-panel"]')
        assert panel.count() == 1, path
        assert panel.get_attribute("data-placement") == placement, path
        assert page.locator('[data-testid="help-form"]').count() == 1, path
        assert page.locator('[data-testid="help-ask-the-city"]').count() == 1, path
    assert page.recorded_errors == []


def test_a_question_is_answered_in_place_with_javascript(
    page, server: BrowserServer, login
) -> None:
    """With JavaScript the answer is rendered in place, without a reload."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    page.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
    page.locator('[data-testid="help-submit"]').click()
    # The quote sits inside a collapsed citation, so it is attached rather
    # than visible.
    page.wait_for_selector('[data-testid="help-quote"]', state="attached")
    assert page.locator('[data-testid="help-turn"]').count() == 1
    body = page.locator('[data-testid="help-panel"]').inner_text()
    assert "ACME Code §14-306" in body
    assert (
        "Matching ACME rule text (not an AI answer)" in body or "Recorded replay" in body
    )  # chat 2: the fence question has a labelled replay fixture
    assert page.recorded_errors == []


def test_a_question_is_answered_without_javascript(
    browser, server: BrowserServer
) -> None:
    """The panel works without JavaScript: the form posts and the page answers."""
    context = browser.new_context(java_script_enabled=False)
    try:
        page = sign_in(context, server, "persona_applicant")
        page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
        page.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
        page.locator('[data-testid="help-submit"]').click()
        page.wait_for_url(lambda url: "/apply?help=" in url)
        assert page.locator('[data-testid="help-turn"]').count() == 1
        assert page.locator('[data-testid="help-quote"]').count() >= 1
        body = page.locator('[data-testid="help-panel"]').inner_text()
        assert "ACME Code §14-306" in body
        assert (
            "Matching ACME rule text (not an AI answer)" in body or "Recorded replay" in body
        )  # chat 2: the fence question has a labelled replay fixture
    finally:
        context.close()


def test_the_application_form_keeps_its_fields_when_the_help_form_is_used(
    browser, server: BrowserServer
) -> None:
    """Without JavaScript the answer opens in its own browsing context.

    The fields and the files the applicant typed stay in the form they were
    typed in, because the help form is a form of its own and its answer opens
    elsewhere.
    """
    context = browser.new_context(java_script_enabled=False)
    try:
        page = sign_in(context, server, "persona_applicant")
        page.goto(f"{server.base_url}/apply/deck_fence", wait_until="domcontentloaded")
        page.locator("#f-applicant_name").fill("Tamsin Aldous")
        page.locator("#f-height_ft").fill("4")
        page.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
        with context.expect_page() as opened:
            page.locator('[data-testid="help-submit"]').click()
        answer = opened.value
        answer.wait_for_load_state("domcontentloaded")
        assert "/apply/help/panel" in answer.url
        assert answer.locator('[data-testid="help-quote"]').count() >= 1
        # The form the applicant typed in still holds what was typed.
        assert page.locator("#f-applicant_name").input_value() == "Tamsin Aldous"
        assert page.locator("#f-height_ft").input_value() == "4"
    finally:
        context.close()


def test_the_ask_the_city_button_works_without_javascript(
    browser, server: BrowserServer
) -> None:
    context = browser.new_context(java_script_enabled=False)
    try:
        page = sign_in(context, server, "persona_applicant")
        page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
        page.locator('[data-testid="help-escalate-question"]').fill(FENCE_QUESTION)
        page.locator('[data-testid="help-ask-the-city"]').click()
        page.wait_for_url(lambda url: "/apply?help=" in url)
        assert page.locator('[data-testid="help-request"]').count() == 1
        status = page.locator('[data-testid="help-request"]').first.get_attribute(
            "data-status"
        )
        assert status == "open"
    finally:
        context.close()


def test_a_suggested_question_fills_the_box_with_javascript(
    page, server: BrowserServer, login
) -> None:
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    page.locator('[data-testid="help-suggestion"]').first.click()
    assert page.locator('[data-testid="help-question"]').input_value() == FENCE_QUESTION
    assert page.recorded_errors == []
