"""The answer of the assistant, as the browser reads it.

The script renders the answer in place; without a script the server renders
the same answer.  Both must read the same: the same sentence, the same
citation and the same rule text behind the same disclosure.
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


def answer_of(page) -> list[dict[str, str]]:
    """Return what the applicant reads of the answer of the last turn."""
    turn = page.locator('[data-testid="help-turn"]').last
    return {
        "label": turn.locator('[data-testid="help-answer-label"]').inner_text(),
        "sentences": turn.locator('[data-testid="help-paragraph-text"]').all_inner_texts(),
        "citations": turn.locator('[data-testid="help-citation-label"]').all_inner_texts(),
        "quotes": turn.locator('[data-testid="help-quote"]').all_inner_texts(),
    }


def test_the_script_and_the_server_render_the_same_answer(browser, server: BrowserServer) -> None:
    """The answer the script writes is the answer the server writes."""
    # With the script the answer is rendered in place.
    with_script = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        page = sign_in(with_script, server, "persona_applicant")
        page.goto(f"{server.base_url}/apply/help/panel", wait_until="domcontentloaded")
        page.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
        page.locator('[data-testid="help-submit"]').click()
        page.wait_for_selector('[data-testid="help-turn"]')
        rendered = answer_of(page)
    finally:
        with_script.close()

    # Without the script the server renders the same answer.
    without_script = browser.new_context(
        viewport={"width": 1280, "height": 900}, java_script_enabled=False
    )
    try:
        page = sign_in(without_script, server, "persona_applicant")
        page.goto(f"{server.base_url}/apply/help/panel", wait_until="domcontentloaded")
        page.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
        with without_script.expect_page() as opened:
            page.locator('[data-testid="help-submit"]').click()
        answer = opened.value
        answer.wait_for_load_state("domcontentloaded")
        server_rendered = answer_of(answer)
    finally:
        without_script.close()

    assert rendered == server_rendered
    assert rendered["sentences"], rendered
    assert "4 ft" in rendered["sentences"][0]


def test_the_answer_shows_no_token_and_no_timestamp(page, server: BrowserServer, login) -> None:
    """What the script writes carries no run figures and no time stamp."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/help/panel", wait_until="domcontentloaded")
    page.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
    page.locator('[data-testid="help-submit"]').click()
    page.wait_for_selector('[data-testid="help-turn"]')
    body = page.locator('[data-testid="help-panel"]').inner_text()
    assert "Recorded demo answer" in body
    assert " in · " not in body
    assert " ms" not in body
    assert page.recorded_errors == []


def test_the_rule_text_opens_behind_its_disclosure(page, server: BrowserServer, login) -> None:
    """The quote of the rule is closed, and a click opens it."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/help/panel", wait_until="domcontentloaded")
    page.locator('[data-testid="help-question"]').fill(FENCE_QUESTION)
    page.locator('[data-testid="help-submit"]').click()
    page.wait_for_selector('[data-testid="help-turn"]')
    quote = page.locator('[data-testid="help-quote"]').first
    assert not quote.is_visible()
    page.locator('[data-testid="help-citation"]').first.click()
    assert quote.is_visible()
    assert "Threshold: 4." in quote.inner_text()
    assert page.recorded_errors == []
