"""The applicant help panel in the browser.

The panel has a page of its own, and it is offered on the application form
and on the tracker.  It works without JavaScript: the question is a form of
its own and the answer re-renders the page.  On the application form and on
the panel's own page the answer opens in a separate browsing context, so the
fields and the files the applicant typed stay exactly as they were.
"""
# REQUIRES: PORTAL-02, UX-02, UX-03, PER-04, SEC-03

from __future__ import annotations

from conftest import BrowserServer

#: The three places the panel is offered.
PLACEMENTS = (
    ("/apply/help/panel", "form"),
)

FENCE_QUESTION = "Do I need a permit for a 6 ft fence?"

#: A question the recorded answer of the assistant declines.
DECLINE_QUESTION = "Will my fence permit be approved?"


def sign_in(context, server: BrowserServer, actor_id: str):
    """Return a signed-in page of a browser context."""
    page = context.new_page()
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator(f'button[data-persona="{actor_id}"]').click()
    # The Applicant now lands on the City of Acme website; staff land on /queue.
    landing = "/city/" if actor_id == "persona_applicant" else "/queue"
    page.wait_for_url(f"{server.base_url}{landing}")
    return page


def test_the_panel_is_offered_on_its_own_page(
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
        # Changed deliberately (the pop-out slice): the form that asks a
        # person at the City moved to the contact page of the City website.
        assert page.locator('[data-testid="help-escalate-form"]').count() == 0, path
    assert page.recorded_errors == []


def test_a_question_is_answered_in_place_with_javascript(
    page, server: BrowserServer, login
) -> None:
    """With JavaScript the answer is rendered in place, without a reload."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/help/panel", wait_until="domcontentloaded")
    page.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
    page.locator('[data-testid="help-submit"]').click()
    # The quote sits inside a collapsed citation, so it is attached rather
    # than visible.
    page.wait_for_selector('[data-testid="help-quote"]', state="attached")
    assert page.locator('[data-testid="help-turn"]').count() == 1
    body = page.locator('[data-testid="help-panel"]').inner_text()
    assert "ACME Code §14-306" in body
    assert (
        "Matching ACME rule text (not an AI answer)" in body or "Recorded demo answer" in body
    )  # chat 2: the fence question has a labelled replay fixture
    assert page.recorded_errors == []


def test_a_question_is_answered_without_javascript(
    browser, server: BrowserServer
) -> None:
    """The panel works without JavaScript: the form posts and the page answers."""
    context = browser.new_context(java_script_enabled=False)
    try:
        page = sign_in(context, server, "persona_applicant")
        page.goto(f"{server.base_url}/apply/help/panel", wait_until="domcontentloaded")
        page.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
        # Without JavaScript the answer opens in its own browsing context.
        with context.expect_page() as opened:
            page.locator('[data-testid="help-submit"]').click()
        answer = opened.value
        answer.wait_for_load_state("domcontentloaded")
        assert "/apply/help/panel" in answer.url
        assert answer.locator('[data-testid="help-turn"]').count() == 1
        assert answer.locator('[data-testid="help-quote"]').count() >= 1
        body = answer.locator('[data-testid="help-panel"]').inner_text()
        assert "ACME Code §14-306" in body
        assert (
            "Matching ACME rule text (not an AI answer)" in body or "Recorded demo answer" in body
        )  # chat 2: the fence question has a labelled replay fixture
    finally:
        context.close()


def test_the_launcher_opens_the_assistant_away_from_the_form(
    browser, server: BrowserServer
) -> None:
    """The assistant opens in its own browsing context.

    The fields and the files the applicant typed stay in the form they were
    typed in, because the assistant has a page of its own.
    """
    context = browser.new_context(java_script_enabled=False)
    try:
        page = sign_in(context, server, "persona_applicant")
        page.goto(f"{server.base_url}/apply/deck_fence", wait_until="domcontentloaded")
        page.locator("#f-applicant_name").fill("Demo Applicant")
        page.locator("#f-height_ft").fill("4")
        with context.expect_page() as opened:
            page.locator('[data-testid="help-launcher"]').click()
        answer = opened.value
        answer.wait_for_load_state("domcontentloaded")
        assert "/apply/help/panel" in answer.url
        assert answer.locator('[data-testid="help-form"]').count() == 1
        # The form the applicant typed in still holds what was typed.
        assert page.locator("#f-applicant_name").input_value() == "Demo Applicant"
        assert page.locator("#f-height_ft").input_value() == "4"
    finally:
        context.close()


def test_the_ask_the_city_button_works_without_javascript(
    browser, server: BrowserServer
) -> None:
    """The form that asks a person at the City is on the contact page."""
    context = browser.new_context(java_script_enabled=False)
    try:
        page = sign_in(context, server, "persona_applicant")
        page.goto(f"{server.base_url}/city/contact", wait_until="domcontentloaded")
        page.locator('[data-testid="contact-question"]').fill(FENCE_QUESTION)
        page.locator('[data-testid="contact-submit"]').click()
        page.wait_for_selector('[data-testid="contact-request"]')
        assert page.locator('[data-testid="contact-request"]').count() == 1
        status = page.locator('[data-testid="contact-request"]').first.get_attribute(
            "data-status"
        )
        assert status == "open"
    finally:
        context.close()


def test_a_suggested_question_fills_the_box_with_javascript(
    page, server: BrowserServer, login
) -> None:
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/help/panel", wait_until="domcontentloaded")
    page.locator('[data-testid="help-suggestion"]').first.click()
    assert page.locator('[data-testid="help-question"]').input_value() == FENCE_QUESTION
    assert page.recorded_errors == []


def test_a_declined_question_shows_the_refusal_with_javascript(
    page, server: BrowserServer, login
) -> None:
    """The refusal of the assistant is shown in place, as it is without it."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/help/panel", wait_until="domcontentloaded")
    page.locator('[data-testid="help-question"]').fill(DECLINE_QUESTION)
    page.locator('[data-testid="help-submit"]').click()
    page.wait_for_selector('[data-testid="help-declined"]', state="visible")
    declined = page.locator('[data-testid="help-declined"]').first
    assert "The assistant did not answer" in declined.inner_text()
    assert "this needs a person" in declined.inner_text()
    assert declined.get_attribute("data-reason") == "needs_a_person"
    # The rule text that matches the question is shown as well.
    assert page.locator('[data-testid="help-citation"]').count() >= 1
    assert page.recorded_errors == []
