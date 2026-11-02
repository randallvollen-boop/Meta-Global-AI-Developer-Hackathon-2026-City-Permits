"""The steward assistant in a browser.

The Data Steward asks the assistant to prepare the work of the queue, reads
the recommendation on a task and accepts it with a click.  The Agent Operator
wakes the assistant; while it sleeps the buttons are off and they say why.

Every control does what it says, and the screens still fit a phone.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, PER-04, SEC-01

from __future__ import annotations

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered
from sqlalchemy import select

from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.models import registry
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.persistence.session import SessionFactory, transaction

#: The source record the demonstration compares with the master records.
RECORD = "PER-AP-0003"


def prepare_queue(server: BrowserServer) -> None:
    """Put the Cedarline tasks in the queue of the demonstration."""
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            seed_cedarline(session)
    finally:
        factory.dispose()


def wake_the_assistant(page, server: BrowserServer, login) -> None:
    """Wake the steward assistant, the way the Agent Operator does."""
    login("persona_agent_operator")
    page.goto(f"{server.base_url}/agent/steward_assist", wait_until="load")
    page.wait_for_selector('[data-testid="agent-toggle"]')
    page.locator('[data-testid="agent-toggle"]').click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=agent-mode]')"
        "?.textContent.trim() === 'awake'"
    )


def open_case(page, server: BrowserServer) -> str:
    """Open the task of one source record and return its address."""
    page.goto(f"{server.base_url}/steward?filter=needs_review", wait_until="load")
    row = page.locator(f'[data-issue-row]:has-text("{RECORD}")').first
    assert row.count() == 1, "the queue holds the task of the source record"
    row.locator('[data-testid="issue-link"]').click()
    page.wait_for_selector('[data-testid="case-summary"]')
    return page.url


def click_action(page, testid: str, action_id: str) -> str:
    """Click a button of the steward assistant and return the message."""
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and f"/ui/actions/{action_id}" in response.url
    ) as posted:
        page.locator(f'[data-testid="{testid}"]').click()
    response = posted.value
    assert response.status == 200, response.text()
    payload = response.json()
    assert payload["status"] == "accepted", payload
    return str(payload.get("message", ""))


# ------------------------------------------------------------------- the queue


def test_the_queue_prepares_the_recommendations_with_a_click(
    page, server: BrowserServer, login
) -> None:
    """One press prepares the work of the tasks and the queue shows it."""
    prepare_queue(server)
    wake_the_assistant(page, server, login)
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward?filter=needs_review", wait_until="load")
    page.wait_for_selector('[data-testid="assistant-prepare"]')
    message = click_action(page, "assistant-prepare", "steward.assist.prepare")
    assert "recommendation" in message
    # The page is read again in place and the rows carry the pill.
    page.wait_for_selector('[data-testid="recommendation-pill"]')
    pill = page.locator('[data-testid="recommendation-pill"]').first.inner_text()
    assert pill.strip() in {"High", "Review", "Held"}
    assert page.locator('[data-testid="recommendation-reason"]').count() > 0
    assert page.recorded_errors == []


def test_the_prepare_button_is_off_while_the_assistant_sleeps(
    page, server: BrowserServer, login
) -> None:
    """A sleeping assistant prepares nothing, and the button says why."""
    prepare_queue(server)
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward?filter=needs_review", wait_until="load")
    button = page.locator('[data-testid="assistant-prepare"]')
    assert button.is_disabled()
    note = page.locator('[data-testid="assistant-sleep-note"]')
    assert note.count() == 1
    assert "Agent Operator must wake it" in note.inner_text()
    assert page.recorded_errors == []


def test_the_operator_may_prepare_the_recommendations(
    page, server: BrowserServer, login
) -> None:
    """The operator wakes the assistant and asks it to prepare the work."""
    prepare_queue(server)
    wake_the_assistant(page, server, login)
    page.goto(f"{server.base_url}/agent/steward_assist", wait_until="load")
    page.wait_for_selector('[data-testid="agent-prepare"]')
    message = click_action(page, "agent-prepare", "steward.assist.prepare")
    assert "recommendation" in message
    assert page.recorded_errors == []


def test_the_operator_may_not_accept_a_recommendation(
    page, server: BrowserServer, login
) -> None:
    """The operator prepares the work; the Data Steward decides it."""
    prepare_queue(server)
    wake_the_assistant(page, server, login)
    page.goto(f"{server.base_url}/agent/steward_assist", wait_until="load")
    click_action(page, "agent-prepare", "steward.assist.prepare")
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            recommendation = session.execute(
                select(StewardRecommendation).where(
                    StewardRecommendation.cleared.is_(False)
                )
            ).scalars().first()
            assert recommendation is not None, "the operator prepared a recommendation"
            recommendation_id = recommendation.id
    finally:
        factory.dispose()
    page.goto(f"{server.base_url}/agent/steward_assist", wait_until="load")
    token = page.locator('input[name="csrf_token"]').first
    assert token.count() == 1
    csrf_token = token.get_attribute("value") or ""
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and "/ui/actions/steward.assist.accept" in response.url
    ) as posted:
        page.evaluate(
            """([token, recommendation]) => {
              const form = document.createElement('form');
              form.method = 'post';
              form.action = '/ui/actions/steward.assist.accept';
              form.innerHTML =
                '<input name="csrf_token" value="' + token + '">' +
                '<input name="action_id" value="steward.assist.accept">' +
                '<input name="next" value="/agent/steward_assist">' +
                '<input name="recommendation_id" value="' + recommendation + '">';
              document.body.appendChild(form);
              form.submit();
            }""",
            [csrf_token, recommendation_id],
        )
    response = posted.value
    assert response.status == 403, response.text()
    assert page.recorded_errors == []


# --------------------------------------------------------------------- the batch


def test_the_batch_opens_with_a_click_and_accepts_with_a_click(
    page, server: BrowserServer, login
) -> None:
    """The steward reads the list first and confirms it with a click."""
    prepare_queue(server)
    wake_the_assistant(page, server, login)
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward?filter=needs_review", wait_until="load")
    click_action(page, "assistant-prepare", "steward.assist.prepare")
    # The button of the batch names the number of the recommendations it holds.
    page.wait_for_selector('[data-testid="assistant-batch-preview"][href]')
    assert "Accept all high-confidence (3)" in page.locator(
        '[data-testid="assistant-batch-preview"]'
    ).inner_text()
    page.locator('[data-testid="assistant-batch-preview"]').click()
    page.wait_for_selector('[data-testid="batch-panel"]')
    assert page.locator('[data-testid="batch-item"]').count() == 3
    message = click_action(page, "assistant-batch-confirm", "steward.assist.batch_accept")
    assert "Accepted 3 of 3" in message
    assert page.recorded_errors == []


def test_the_batch_button_is_off_when_nothing_is_sure(
    page, server: BrowserServer, login
) -> None:
    """An empty batch is a disabled button and a note that says why."""
    prepare_queue(server)
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward?filter=needs_review", wait_until="load")
    button = page.locator('[data-testid="assistant-batch-preview"]')
    assert button.is_disabled()
    note = page.locator('[data-testid="assistant-batch-note"]')
    assert note.count() == 1
    assert "sure enough" in note.inner_text()
    assert page.recorded_errors == []


def test_the_button_of_muse_is_off_without_a_credential(
    page, server: BrowserServer, login
) -> None:
    """Without a credential the button of Muse is off and the note says why."""
    prepare_queue(server)
    wake_the_assistant(page, server, login)
    login("persona_data_steward")
    open_case(page, server)
    click_action(page, "assistant-recommend", "steward.assist.recommend")
    # The button of Muse sits behind the disclosure of the panel.
    page.locator('[data-testid="assistant-more"] > summary').click()
    page.wait_for_selector('[data-testid="assistant-explain"]')
    assert page.locator('[data-testid="assistant-explain"]').is_disabled()
    note = page.locator('[data-testid="assistant-explain-note"]')
    assert note.count() == 1
    assert "No provider credential is configured" in note.inner_text()
    assert page.recorded_errors == []


# ----------------------------------------------------------------- the task page


def test_the_task_page_gets_a_recommendation_with_a_click(
    page, server: BrowserServer, login
) -> None:
    """The steward asks for the work of one task and reads the evidence."""
    prepare_queue(server)
    wake_the_assistant(page, server, login)
    login("persona_data_steward")
    open_case(page, server)
    page.wait_for_selector('[data-testid="assistant-recommend"]')
    message = click_action(page, "assistant-recommend", "steward.assist.recommend")
    assert "recommendation" in message
    page.wait_for_selector('[data-testid="assistant-pill"]')
    assert page.locator('[data-testid="assistant-evidence"]').count() == 1
    assert page.locator('[data-testid="assistant-accept"]').count() == 1
    assert page.recorded_errors == []


def test_the_task_page_accepts_the_recommendation_with_a_click(
    page, server: BrowserServer, login
) -> None:
    """The steward decides, and the link of the source record is approved."""
    prepare_queue(server)
    wake_the_assistant(page, server, login)
    login("persona_data_steward")
    open_case(page, server)
    click_action(page, "assistant-recommend", "steward.assist.recommend")
    page.wait_for_selector('[data-testid="assistant-accept"]')
    reason = page.locator('[data-testid="assistant-reason-field"]')
    reason.fill("the evidence agrees with the master record")
    message = click_action(page, "assistant-accept", "steward.assist.accept")
    assert "accepted" in message.lower()
    page.wait_for_selector('[data-testid="assistant-empty"]')
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            links = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == RECORD
                )
            ).scalars().all()
            assert links[-1].link_status == "approved"
            assert links[-1].decision_actor_id == "persona_data_steward"
    finally:
        factory.dispose()
    assert page.recorded_errors == []


def test_the_task_page_clears_the_recommendation_with_a_click(
    page, server: BrowserServer, login
) -> None:
    """A recommendation the steward does not want is cleared."""
    prepare_queue(server)
    wake_the_assistant(page, server, login)
    login("persona_data_steward")
    open_case(page, server)
    click_action(page, "assistant-recommend", "steward.assist.recommend")
    # The button that clears the recommendation sits behind the disclosure.
    page.locator('[data-testid="assistant-more"] > summary').click()
    page.wait_for_selector('[data-testid="assistant-clear"]')
    message = click_action(page, "assistant-clear", "steward.assist.clear")
    assert "cleared" in message.lower()
    page.wait_for_selector('[data-testid="assistant-empty"]')
    assert page.recorded_errors == []


def test_the_operator_wakes_the_assistant(page, server: BrowserServer, login) -> None:
    """The Agent Operator holds the wake and sleep switch."""
    login("persona_agent_operator")
    page.goto(f"{server.base_url}/agents", wait_until="load")
    assert "Steward assistant" in page.content()
    page.goto(f"{server.base_url}/agent/steward_assist", wait_until="load")
    page.wait_for_selector('[data-testid="agent-toggle"]')
    assert page.locator('[data-testid="agent-mode"]').inner_text().strip() == "asleep"
    page.locator('[data-testid="agent-toggle"]').click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=agent-mode]')"
        "?.textContent.trim() === 'awake'"
    )
    assert page.recorded_errors == []


# ----------------------------------------------------------------------- a phone


def test_the_queue_fits_a_phone(viewport_390, server: BrowserServer, login) -> None:
    """At 390 pixels the button of the assistant stays inside the screen."""
    prepare_queue(server)
    login("persona_data_steward")
    page = viewport_390
    page.goto(f"{server.base_url}/steward?filter=needs_review", wait_until="load")
    assert page.viewport_size == {"width": 390, "height": 844}
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert_not_covered(page, page.locator('[data-testid="assistant-prepare"]'))
    # The button of the batch and the agreement figure stay inside too.
    assert_not_covered(page, page.locator('[data-testid="assistant-batch-preview"]'))
    assert_not_covered(page, page.locator('[data-testid="agreement-panel"]'))
    assert page.recorded_errors == []


def test_the_task_page_fits_a_phone(viewport_390, server: BrowserServer, login) -> None:
    """At 390 pixels the panel of the assistant stays inside the screen."""
    prepare_queue(server)
    wake_the_assistant(viewport_390, server, login)
    login("persona_data_steward")
    open_case(viewport_390, server)
    click_action(viewport_390, "assistant-recommend", "steward.assist.recommend")
    viewport_390.wait_for_selector('[data-testid="assistant-accept"]')
    assert_no_horizontal_overflow(viewport_390)
    assert_not_covered(viewport_390, viewport_390.locator("main h1").first)
    assert_not_covered(viewport_390, viewport_390.locator('[data-testid="assistant-accept"]'))
    # The button of Muse and the note beside it stay inside too.
    viewport_390.locator('[data-testid="assistant-more"] > summary').click()
    assert_not_covered(viewport_390, viewport_390.locator('[data-testid="assistant-explain"]'))
    assert_not_covered(
        viewport_390, viewport_390.locator('[data-testid="assistant-explain-note"]')
    )
    assert viewport_390.recorded_errors == []
