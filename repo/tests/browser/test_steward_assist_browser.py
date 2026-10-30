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


def test_the_operator_may_not_press_the_steward_buttons(
    page, server: BrowserServer, login
) -> None:
    """The run grant of the assistant belongs to the Data Steward alone."""
    prepare_queue(server)
    wake_the_assistant(page, server, login)
    token = page.locator('[data-testid="agent-toggle-form"] input[name="csrf_token"]')
    assert token.count() == 1
    csrf_token = token.get_attribute("value") or ""
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and "/ui/actions/steward.assist.prepare" in response.url
    ) as posted:
        page.evaluate(
            """(token) => {
              const form = document.createElement('form');
              form.method = 'post';
              form.action = '/ui/actions/steward.assist.prepare';
              form.innerHTML =
                '<input name="csrf_token" value="' + token + '">' +
                '<input name="action_id" value="steward.assist.prepare">' +
                '<input name="next" value="/agents">';
              document.body.appendChild(form);
              form.submit();
            }""",
            csrf_token,
        )
    response = posted.value
    assert response.status == 403, response.text()
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
    assert viewport_390.recorded_errors == []
