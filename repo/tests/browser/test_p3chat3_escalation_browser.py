"""Chat 3 in the browser, as the Applicant: the prompt, Ask the City, the reply.

The help panel opens over the page of the applicant, and it has a page of its
own for the applicant who has no script.  After three questions the assistant
could not answer it prompts the applicant to ask a person at the City; the
button itself is always there.  The Administrator's reply reaches the
applicant, with and without JavaScript.
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
            for number, question in enumerate(NONSENSE, start=1):
                page.locator('[data-testid="help-question"]').fill(question)
                page.locator('[data-testid="help-submit"]').click()
                page.wait_for_function(
                    "(n) => document.querySelectorAll('[data-testid=help-turn]').length === n", arg=number
                )
                prompts = page.locator('[data-testid="help-escalation-prompt"]').count()
                assert prompts == (1 if number == 3 else 0), (placement, number)
            # Changed deliberately (the pop-out slice): the prompt points at
            # the one contact page of the City website.
            link = page.locator('[data-testid="help-escalation-link"]')
            assert link.count() == 1, placement
            assert "/city/contact" in link.get_attribute("href")
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
        # The prompt leads to the contact page, and the last question of the
        # conversation is the one the box starts with.
        page.locator('[data-testid="help-escalation-link"]').click()
        page.wait_for_url(f"{server.base_url}/city/contact*")
        assert page.locator('[data-testid="contact-question"]').input_value() == NONSENSE[-1]
        page.locator('[data-testid="contact-submit"]').click()
        page.wait_for_selector('[data-testid="contact-request"]')
        request = page.locator('[data-testid="contact-request"]').first
        assert request.get_attribute("data-status") == "open"
        assert NONSENSE[-1] in request.inner_text()
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
        current.locator('[data-testid="help-escalation-link"]').click()
        current.wait_for_load_state("domcontentloaded")
        assert "/city/contact" in current.url
        current.locator('[data-testid="contact-submit"]').click()
        current.wait_for_selector('[data-testid="contact-request"]')
        assert current.locator('[data-testid="contact-request"]').first.get_attribute(
            "data-status"
        ) == "open"
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
        current.locator('[data-testid="help-escalation-link"]').click()
        current.wait_for_load_state("domcontentloaded")
        assert "/city/contact" in current.url
        current.locator('[data-testid="contact-submit"]').click()
        current.wait_for_selector('[data-testid="contact-request"]')
        assert current.locator('[data-testid="contact-request"]').first.get_attribute(
            "data-status"
        ) == "open"
        assert page.locator("#f-applicant_name").input_value() == "Demo Applicant"  # the form is untouched
    finally:
        context.close()


def test_the_administrators_reply_reaches_the_applicant(browser, server: BrowserServer) -> None:
    applicant_context = browser.new_context(viewport={"width": 1280, "height": 900})
    admin_context = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        applicant = sign_in(applicant_context, server, "persona_applicant")
        applicant.goto(f"{server.base_url}/apply/track?ref=SYN-APP-005", wait_until="domcontentloaded")
        # Changed deliberately (the panel slice): the tracker has no panel of
        # its own; the launcher opens the assistant over the page.
        applicant.locator('[data-testid="help-launcher"]').click()
        applicant.wait_for_selector('[data-testid="help-panel"]')
        for question in NONSENSE:
            applicant.locator('[data-testid="help-question"]').fill(question)
            applicant.locator('[data-testid="help-submit"]').click()
            applicant.wait_for_function(
                "(q) => document.body.innerText.includes(q)", arg=question
            )
        # The assistant could not answer, so the panel points at the contact
        # page, which continues the conversation of the case.
        assert applicant.locator('[data-testid="help-escalation-prompt"]').count() == 1
        # The address carries the conversation of the applicant.
        tracker_url = applicant.url
        applicant.locator('[data-testid="help-escalation-link"]').click()
        applicant.wait_for_url(f"{server.base_url}/city/contact*")
        assert applicant.locator('[data-testid="contact-question"]').input_value() == NONSENSE[-1]
        applicant.locator('[data-testid="contact-submit"]').click()
        applicant.wait_for_selector('[data-testid="contact-request"]')

        admin = sign_in(admin_context, server, "persona_city_administrator")
        admin.goto(f"{server.base_url}/ops/support", wait_until="domcontentloaded")
        card = admin.locator('[data-testid="help-request-card"]').first
        assert NONSENSE[-1] in card.inner_text()
        assert "SYN-APP-005" in card.inner_text()
        card.locator('[data-testid="help-reply"]').fill(REPLY)
        card.locator('[data-testid="help-answer"]').click()
        admin.wait_for_function(
            "() => { const region = document.querySelector('[data-testid=feedback-message]');"
            " return region !== null && region.textContent.trim() !== ''; }"
        )

        # the reply reaches the applicant as a message of the City on the case
        applicant.goto(tracker_url, wait_until="domcontentloaded")
        body = applicant.inner_text("body")
        assert REPLY in body
        # and the panel of the applicant shows the answer of the City
        applicant.locator('[data-testid="help-launcher"]').click()
        applicant.wait_for_selector('[data-testid="help-panel"]')
        applicant.locator('[data-testid="help-more"] > summary').click()
        assert REPLY in applicant.locator('[data-testid="help-panel"]').inner_text()
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
