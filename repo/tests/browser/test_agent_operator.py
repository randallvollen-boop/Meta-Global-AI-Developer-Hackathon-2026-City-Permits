"""Phone layout checks and the saved state of the Agent Operator's admin part."""

from __future__ import annotations

import json

from conftest import assert_no_horizontal_overflow, assert_not_covered

SAVED_MESSAGE = "City worker agent access was saved."


def test_role_permissions_fit_at_390(viewport_390, login) -> None:
    page = viewport_390
    login("persona_city_administrator")
    page.goto(page.url.split("/overview")[0] + "/admin?tab=users", wait_until="domcontentloaded")
    table = page.locator("[data-testid='agent-role-permissions-table']")
    assert table.is_visible()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, table)


def test_the_administrator_saves_the_role_permissions(page, server, login) -> None:
    """The City Administrator ticks the box, saves it and sees it saved."""
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/admin?tab=users", wait_until="domcontentloaded")
    checkbox = page.locator("input[name='city_worker_enabled']")
    assert not checkbox.is_checked()
    checkbox.check()
    page.fill("#opr-role-reason", "Winter coverage")
    with page.expect_response(
        lambda response: "/ui/actions/admin.role.permissions" in response.url
        and response.request.method == "POST"
    ) as answered:
        page.click("[data-testid='admin-role-permissions-save']")
    response = answered.value
    assert response.status == 200, response.text()
    payload = response.json()
    assert payload["status"] == "accepted", payload
    assert payload["message"] == SAVED_MESSAGE
    page.wait_for_function(
        "() => { const region = document.querySelector('[data-testid=feedback-message]');"
        f" return region !== null && region.textContent.trim() === '{SAVED_MESSAGE}'; }}"
    )
    # The saved state is the one the server holds, not the state of the form.
    page.reload(wait_until="domcontentloaded")
    assert page.locator("input[name='city_worker_enabled']").is_checked()


def test_the_operator_wakes_and_runs_the_agent_at_390(viewport_390, server, login) -> None:
    """The run controls work on a phone, and the batch says what it will do."""
    page = viewport_390
    login("persona_agent_operator")
    # A case arrives from outside the City and waits for the intake agent.
    response = page.request.post(
        f"{server.base_url}/api/intake/simulate",
        data=json.dumps({"scenario": "deck-high"}),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()
    page.goto(f"{server.base_url}/agent/intake", wait_until="domcontentloaded")
    button = page.locator("[data-testid='agent-run-all']")
    # The agent sleeps, so the run button is off.
    assert button.is_disabled()
    with page.expect_response(
        lambda answer: "/ui/actions/agent.toggle" in answer.url
    ) as answered:
        page.click("[data-testid='agent-toggle']")
    payload = answered.value.json()
    assert payload["status"] == "accepted", payload
    # The awake state is the one the server holds.
    page.reload(wait_until="domcontentloaded")
    button = page.locator("[data-testid='agent-run-all']")
    assert button.is_enabled()
    assert button.inner_text().strip() == "Process next 20"
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, button)
    # The button runs the waiting case and says how many it ran.
    with page.expect_response(
        lambda answer: "/ui/actions/agent.run.intake" in answer.url
    ) as answered:
        button.click()
    payload = answered.value.json()
    assert payload["status"] == "accepted", payload
    assert payload["message"] == "The intake agent ran on 1 waiting case(s)."
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1"))
