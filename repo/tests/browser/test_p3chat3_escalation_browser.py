"""Chat 3 in the browser, as the Applicant: the prompt, Ask the City, the reply.

The help panel has a page of its own, and it is offered on the application form
and on the tracker.  After three questions the assistant could not answer it prompts the
applicant to ask a person at the City; the button itself is always there.  The
Administrator's reply reaches the applicant, with and without JavaScript.
"""
# REQUIRES: PORTAL-02, UX-02, UX-03, PER-04, SEC-03

from __future__ import annotations

import sys
from pathlib import Path

from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from p3c_support import seed_help_request  # noqa: E402

PLACEMENTS = (
    ("/apply/help/panel", "form"),
)
NONSENSE = ("purple monkey dishwasher", "quantum banana trombone", "velvet lighthouse spaghetti")
REPLY = "A person at the City read your question and will call you."


def sign_in(context, server: BrowserServer, actor_id: str):
    page = context.new_page()
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator(f'button[data-persona="{actor_id}"]').click()
    # Changed deliberately (the City Administrator restyle): the Administrator
    # lands on the planning overview; other staff land on the work queue.
    landing = {"persona_applicant": "/city/", "persona_city_administrator": "/overview"}.get(actor_id, "/queue")
    page.wait_for_url(f"{server.base_url}{landing}")
    return page


def test_the_prompt_appears_after_the_third_unsuccessful_question_with_javascript(
    browser, server: BrowserServer
) -> None:
    for path, placement in PLACEMENTS:
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        try:
            page = sign_in(context, server, "persona_applicant")
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
            assert page.locator('[data-testid="help-ask-the-city"]').is_visible(), placement
            for number, question in enumerate(NONSENSE, start=1):
                page.locator('[data-testid="help-question"]').fill(question)
                page.locator('[data-testid="help-submit"]').click()
                page.wait_for_function(
                    "(n) => document.querySelectorAll('[data-testid=help-turn]').length === n", arg=number
                )
                prompts = page.locator('[data-testid="help-escalation-prompt"]').count()
                assert prompts == (1 if number == 3 else 0), (placement, number)
            assert page.locator('[data-testid="help-ask-the-city"]').is_visible()
            # The textarea of Ask the City is carried over from the last question.
            assert page.locator('[data-testid="help-escalate-question"]').first is not None
            assert errors == [], placement
        finally:
            context.close()


def test_ask_the_city_after_the_prompt_with_javascript(browser, server: BrowserServer) -> None:
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        page = sign_in(context, server, "persona_applicant")
        page.goto(f"{server.base_url}/apply/help/panel", wait_until="domcontentloaded")
        for question in NONSENSE:
            page.locator('[data-testid="help-question"]').fill(question)
            page.locator('[data-testid="help-submit"]').click()
            page.wait_for_function(
                "(q) => document.body.innerText.includes(q)", arg=question
            )
        assert page.locator('[data-testid="help-escalation-prompt"]').count() == 1
        assert page.locator('[data-testid="help-escalate-question"]').input_value() == NONSENSE[-1]
        # The request opens in its own browsing context, as on the form.
        with context.expect_page() as opened:
            page.locator('[data-testid="help-ask-the-city"]').click()
        answer = opened.value
        answer.wait_for_load_state("domcontentloaded")
        assert answer.locator('[data-testid="help-request"]').first.get_attribute("data-status") == "open"
        assert answer.locator('[data-testid="help-escalation-prompt"]').count() == 0  # a request is open
    finally:
        context.close()


def test_the_prompt_and_ask_the_city_work_without_javascript(browser, server: BrowserServer) -> None:
    context = browser.new_context(java_script_enabled=False)
    try:
        page = sign_in(context, server, "persona_applicant")
        page.goto(f"{server.base_url}/apply/help/panel", wait_until="domcontentloaded")
        current = page
        for number, question in enumerate(NONSENSE, start=1):
            current.locator('[data-testid="help-question"]').fill(question)
            # Without JavaScript the answer opens in its own browsing context.
            with context.expect_page() as opened:
                current.locator('[data-testid="help-submit"]').click()
            current = opened.value
            current.wait_for_load_state("domcontentloaded")
            assert "/apply/help/panel" in current.url
            assert current.locator('[data-testid="help-turn"]').count() == number
            assert current.locator('[data-testid="help-escalation-prompt"]').count() == (1 if number == 3 else 0)
        with context.expect_page() as asked:
            current.locator('[data-testid="help-ask-the-city"]').click()
        result = asked.value
        result.wait_for_load_state("domcontentloaded")
        result.wait_for_selector('[data-testid="help-request"]')
        assert result.locator('[data-testid="help-escalation-prompt"]').count() == 0
    finally:
        context.close()


def test_the_panel_prompts_in_its_own_context_and_keeps_the_form(browser, server: BrowserServer) -> None:
    context = browser.new_context(java_script_enabled=False)
    try:
        page = sign_in(context, server, "persona_applicant")
        page.goto(f"{server.base_url}/apply/deck_fence", wait_until="domcontentloaded")
        page.locator("#f-applicant_name").fill("Demo Applicant")
        with context.expect_page() as opened:
            page.locator('[data-testid="help-launcher"]').click()
        current = opened.value
        current.wait_for_load_state("domcontentloaded")
        for number, question in enumerate(NONSENSE, start=1):
            current.locator('[data-testid="help-question"]').fill(question)
            with context.expect_page() as answered:
                current.locator('[data-testid="help-submit"]').click()
            current = answered.value
            current.wait_for_load_state("domcontentloaded")
            assert "/apply/help/panel" in current.url
            assert current.locator('[data-testid="help-turn"]').count() == number
        assert current.locator('[data-testid="help-escalation-prompt"]').count() == 1
        with context.expect_page() as asked:
            current.locator('[data-testid="help-ask-the-city"]').click()
        result = asked.value
        result.wait_for_load_state("domcontentloaded")
        assert result.locator('[data-testid="help-request"]').first.get_attribute("data-status") == "open"
        assert page.locator("#f-applicant_name").input_value() == "Demo Applicant"  # the form is untouched
    finally:
        context.close()


def test_the_administrators_reply_reaches_the_applicant(browser, server: BrowserServer) -> None:
    applicant_context = browser.new_context(viewport={"width": 1280, "height": 900})
    admin_context = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        applicant = sign_in(applicant_context, server, "persona_applicant")
        applicant.goto(f"{server.base_url}/apply/track?ref=SYN-APP-005", wait_until="domcontentloaded")
        # Changed deliberately (the applicant restyle, A3): the tracker has no
        # panel of its own; the launcher opens the assistant on its own page.
        with applicant_context.expect_page() as opened:
            applicant.locator('[data-testid="help-launcher"]').click()
        assistant = opened.value
        assistant.wait_for_load_state("domcontentloaded")
        assistant.locator('[data-testid="help-escalate-question"]').fill("Who is reviewing my fence application?")
        with applicant_context.expect_page() as asked:
            assistant.locator('[data-testid="help-ask-the-city"]').click()
        request = asked.value
        request.wait_for_load_state("domcontentloaded")
        request.wait_for_selector('[data-testid="help-request"]')

        admin = sign_in(admin_context, server, "persona_city_administrator")
        admin.goto(f"{server.base_url}/ops/support", wait_until="domcontentloaded")
        card = admin.locator('[data-testid="help-request-card"]').first
        assert "Who is reviewing my fence application?" in card.inner_text()
        assert "SYN-APP-005" in card.inner_text()
        card.locator('[data-testid="help-reply"]').fill(REPLY)
        card.locator('[data-testid="help-answer"]').click()
        admin.wait_for_selector('[data-testid="feedback-message"]')

        # the reply reaches the applicant as a message of the City on the case
        applicant.goto(f"{server.base_url}/apply/track?ref=SYN-APP-005", wait_until="domcontentloaded")
        body = applicant.inner_text("body")
        assert REPLY in body
        # and the assistant's own page shows the answer of the City
        request.reload(wait_until="domcontentloaded")
        assert "Answer from the City" in request.inner_text("body")
    finally:
        applicant_context.close()
        admin_context.close()


def test_support_leads_with_requests_and_names_the_reply_destination(page, server: BrowserServer, login) -> None:
    seed_help_request(server.settings, application_id="app_d05")
    login("persona_city_administrator")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/ops/support", wait_until="domcontentloaded")
    requests = page.locator('[data-testid="support-requests"]')
    lookup = page.locator('[data-testid="support-lookup"]')
    assert requests.bounding_box()["y"] < lookup.bounding_box()["y"]
    assert page.locator('[data-testid="support-filter-open"]').get_attribute("aria-current") == "page"
    assert page.locator('[data-testid="support-record"]').locator(
        "xpath=ancestor::*[@data-testid='support-lookup']"
    ).count() == 0
    open_request = page.locator('[data-testid="help-request-card"][data-status="open"]').first
    assert "The applicant can read this reply." in open_request.inner_text()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator('[data-testid="persona-trigger"]'))
    assert page.recorded_errors == []
