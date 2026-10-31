"""Phone layout checks and the saved state of the Agent Operator's admin part."""

from __future__ import annotations

import json

from conftest import assert_no_horizontal_overflow, assert_not_covered

from acme_city.persistence.models import permit
from acme_city.persistence.session import SessionFactory, transaction

SAVED_MESSAGE = "City worker agent access was saved."


def _set_case_status(server, application_id: str, status: str) -> None:
    """Set the state of one case in the database of the fixture.

    The operator cannot archive a case, so the test does it the way the
    administration does: the row of the case carries the state.
    """
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(permit.Application, application_id)
            assert row is not None, application_id
            row.status = status
    finally:
        factory.dispose()


def _run_the_intake_agent(page, server) -> None:
    """Let the intake agent work on a case that arrived from outside."""
    response = page.request.post(
        f"{server.base_url}/api/intake/simulate",
        data=json.dumps({"scenario": "deck-high"}),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()
    page.goto(f"{server.base_url}/agent/intake", wait_until="domcontentloaded")
    with page.expect_response(
        lambda answer: "/ui/actions/agent.toggle" in answer.url
    ) as answered:
        page.click("[data-testid='agent-toggle']")
    assert answered.value.json()["status"] == "accepted"
    page.reload(wait_until="domcontentloaded")
    with page.expect_response(
        lambda answer: "/ui/actions/agent.run.intake" in answer.url
    ) as answered:
        page.click("[data-testid='agent-run-all']")
    assert answered.value.json()["status"] == "accepted"


def _wake_the_agent(page, server, agent_key: str) -> None:
    """Wake one agent on its own screen."""
    page.goto(f"{server.base_url}/agent/{agent_key}", wait_until="domcontentloaded")
    with page.expect_response(
        lambda answer: "/ui/actions/agent.toggle" in answer.url
    ) as answered:
        page.click("[data-testid='agent-toggle']")
    assert answered.value.json()["status"] == "accepted"
    page.reload(wait_until="domcontentloaded")


def _break_the_facts(server, application_id: str) -> dict:
    """Make the classifier of the intake agent stop, and return the facts.

    The classifier reads the facts of the case as a mapping.  Facts that are
    not a mapping stop the node, and the attempt is recorded as failed.
    """
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(permit.Application, application_id)
            assert row is not None, application_id
            facts = dict(row.submitted_facts or {})
            row.submitted_facts = ["the facts of the case are not a mapping"]
            return facts
    finally:
        factory.dispose()


def _restore_the_facts(server, application_id: str, facts: dict) -> None:
    """Put the facts of one case back the way they were."""
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(permit.Application, application_id)
            assert row is not None, application_id
            row.submitted_facts = facts
    finally:
        factory.dispose()


def _fail_a_case(page, server) -> str:
    """Let the intake agent stop on a case and return the case it stopped on.

    The case is archived while the operator is looking at the screen, so the
    run stops and the failure is recorded on the work of the case.
    """
    response = page.request.post(
        f"{server.base_url}/api/intake/simulate",
        data=json.dumps({"scenario": "deck-high"}),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()
    _wake_the_agent(page, server, "intake")
    page.goto(f"{server.base_url}/agent/intake", wait_until="domcontentloaded")
    row = page.locator("[data-testid='agent-waiting-row']").first
    application_id = row.get_attribute("data-application-id")
    assert application_id
    # The case is archived, so the run of the agent stops.
    _set_case_status(server, application_id, "archived")
    with page.expect_response(
        lambda answer: "/ui/actions/agent.run.intake" in answer.url
    ) as answered:
        page.click("[data-testid='agent-run-one']")
    payload = answered.value.json()
    assert payload["status"] == "accepted", payload
    assert "stopped on" in payload["message"], payload
    return application_id


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


def test_the_operator_processes_one_waiting_case_at_390(
    viewport_390, server, login
) -> None:
    """The row button works one case, and the case leaves the waiting list."""
    page = viewport_390
    login("persona_agent_operator")
    response = page.request.post(
        f"{server.base_url}/api/intake/simulate",
        data=json.dumps({"scenario": "deck-high"}),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()
    _wake_the_agent(page, server, "intake")
    row = page.locator("[data-testid='agent-waiting-row']").first
    application_id = row.get_attribute("data-application-id")
    assert application_id
    button = page.locator("[data-testid='agent-run-one']").first
    assert button.is_enabled()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, button)
    with page.expect_response(
        lambda answer: "/ui/actions/agent.run.intake" in answer.url
    ) as answered:
        button.click()
    payload = answered.value.json()
    assert payload["status"] == "accepted", payload
    assert payload["message"] == f"The intake agent ran on {application_id}."
    # The case was worked, so it does not wait for the agent any more.
    page.reload(wait_until="domcontentloaded")
    assert page.locator("[data-testid='agent-waiting-empty']").is_visible()
    assert_no_horizontal_overflow(page)


def test_the_operator_runs_the_adjudication_batch_at_390(
    viewport_390, server, login
) -> None:
    """The batch of the adjudication agent runs the cases that are in review."""
    page = viewport_390
    login("persona_agent_operator")
    # A case arrives and the intake agent works it, so it waits for review.
    _run_the_intake_agent(page, server)
    _wake_the_agent(page, server, "adjudication")
    row = page.locator("[data-testid='agent-waiting-row']").first
    application_id = row.get_attribute("data-application-id")
    assert application_id
    button = page.locator("[data-testid='agent-run-all']")
    assert button.is_enabled()
    assert button.inner_text().strip() == "Process next 20"
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, button)
    with page.expect_response(
        lambda answer: "/ui/actions/agent.run.adjudication" in answer.url
    ) as answered:
        button.click()
    payload = answered.value.json()
    assert payload["status"] == "accepted", payload
    assert payload["message"] == "The adjudication agent ran on 1 case(s)."
    assert payload["affected"] == [application_id]
    assert_no_horizontal_overflow(page)


def test_the_operator_runs_one_case_in_review_at_390(
    viewport_390, server, login
) -> None:
    """The row button of the adjudication agent works one case in review."""
    page = viewport_390
    login("persona_agent_operator")
    _run_the_intake_agent(page, server)
    _wake_the_agent(page, server, "adjudication")
    row = page.locator("[data-testid='agent-waiting-row']").first
    application_id = row.get_attribute("data-application-id")
    assert application_id
    button = page.locator("[data-testid='agent-run-one']").first
    assert button.is_enabled()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, button)
    with page.expect_response(
        lambda answer: "/ui/actions/agent.run.adjudication" in answer.url
    ) as answered:
        button.click()
    payload = answered.value.json()
    assert payload["status"] == "accepted", payload
    assert payload["message"] == f"The adjudication agent ran on {application_id}."
    assert_no_horizontal_overflow(page)


def test_the_run_history_shows_the_recorded_runs_at_390(viewport_390, server, login) -> None:
    """The history shows the run of the agent and the engine that produced it."""
    page = viewport_390
    login("persona_agent_operator")
    _run_the_intake_agent(page, server)
    page.goto(f"{server.base_url}/agents/runs", wait_until="domcontentloaded")
    rows = page.locator("[data-testid='agent-run-row']")
    assert rows.count() >= 1
    assert "Built in logic" in rows.first.inner_text()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("[data-testid='agent-run-history']"))
    # The filter of the other agent narrows the history to nothing.
    page.select_option("[data-testid='run-filter-agent']", "adjudication")
    page.click("[data-testid='run-filter-apply']")
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("[data-testid='agent-run-row']").count() == 0
    assert page.locator("[data-testid='agent-run-empty']").is_visible()
    assert_no_horizontal_overflow(page)
    # Clearing the filters brings the run back.
    page.click("[data-testid='run-filter-clear']")
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("[data-testid='agent-run-row']").count() >= 1
    assert_no_horizontal_overflow(page)


def test_the_case_summary_shows_the_work_of_the_agent_at_390(viewport_390, server, login) -> None:
    """The case summary shows the revision, the state and the recorded runs."""
    page = viewport_390
    login("persona_agent_operator")
    _run_the_intake_agent(page, server)
    page.goto(f"{server.base_url}/agents/runs", wait_until="domcontentloaded")
    link = page.locator("[data-testid='agent-run-case-link']").first
    link.click()
    page.wait_for_load_state("domcontentloaded")
    summary = page.locator("[data-testid='agent-case-summary']")
    assert summary.is_visible()
    assert page.locator("[data-testid='agent-case-reference']").inner_text().strip()
    assert page.locator("[data-testid='agent-case-revision']").inner_text().strip()
    assert page.locator("[data-testid='agent-case-engine']").inner_text().strip() == (
        "Built in logic"
    )
    assert page.locator("[data-testid='agent-case-run']").count() >= 1
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, summary)


def test_the_agent_screens_fit_at_390_for_the_operator(viewport_390, server, login) -> None:
    """Both agent screens read well on a phone."""
    page = viewport_390
    login("persona_agent_operator")
    for path in ("/agent/intake", "/agent/adjudication"):
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert page.locator("[data-testid='agent-state']").is_visible()
        assert page.locator("[data-testid='agent-policy']").inner_text().strip()
        assert page.locator("[data-testid='agent-engine']").inner_text().strip()
        assert_no_horizontal_overflow(page)
        assert_not_covered(page, page.locator("[data-testid='agent-kpis']"))
        assert_not_covered(page, page.locator("[data-testid='agent-waiting']"))
    # The screen of an agent with automatic processing on reads well as well.
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/admin?tab=agent_processing", wait_until="domcontentloaded")
    page.locator("input[name='keep_awake']").check()
    page.fill("#opr-runs-per-hour", "42")
    page.fill("#opr-processing-reason", "Evening coverage")
    with page.expect_response(
        lambda response: "/ui/actions/admin.agent.processing" in response.url
        and response.request.method == "POST"
    ) as answered:
        page.click("[data-testid='admin-agent-processing-save']")
    assert answered.value.json()["status"] == "accepted"
    login("persona_agent_operator")
    page.goto(f"{server.base_url}/agent/intake", wait_until="domcontentloaded")
    assert "an awake agent works new arrivals" in page.inner_text("body")
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("[data-testid='agent-state']"))


def test_the_agent_screens_fit_at_390_for_a_city_worker(viewport_390, server, login) -> None:
    """A reviewer with the City worker option may open the agent screens."""
    page = viewport_390
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/admin?tab=users", wait_until="domcontentloaded")
    page.locator("input[name='city_worker_enabled']").check()
    page.fill("#opr-role-reason", "Winter coverage")
    with page.expect_response(
        lambda response: "/ui/actions/admin.role.permissions" in response.url
        and response.request.method == "POST"
    ) as answered:
        page.click("[data-testid='admin-role-permissions-save']")
    assert answered.value.json()["status"] == "accepted"
    login("persona_permit_reviewer")
    for path in ("/agent/intake", "/agent/adjudication"):
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert page.locator("[data-testid='agent-state']").is_visible()
        assert page.locator("[data-testid='agent-run-all']").is_visible()
        assert_no_horizontal_overflow(page)
        assert_not_covered(page, page.locator("[data-testid='agent-waiting']"))


def test_the_administrator_saves_the_processing_settings(page, server, login) -> None:
    """The City Administrator ticks the box, saves it and sees it saved."""
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/admin?tab=agent_processing", wait_until="domcontentloaded")
    assert page.locator("[data-testid='admin-agent-processing']").is_visible()
    # The tab of the administration screen carries the current section.
    tab = page.locator("[data-tab='agent_processing']")
    assert tab.get_attribute("aria-current") == "page"
    # The deployment sends no provider call, so the allowance reads zero.  The
    # allowance and the engine sit behind More details (demo polish, AD1), so
    # the disclosure is opened before they are read.
    page.locator("[data-testid='admin-agent-processing-more'] > summary").click()
    assert page.locator("[data-testid='admin-muse-cap']").inner_text().strip() == "0"
    assert page.locator("[data-testid='admin-engine']").inner_text().strip() == (
        "Built in logic"
    )
    checkbox = page.locator("input[name='keep_awake']")
    assert not checkbox.is_checked()
    checkbox.check()
    page.fill("#opr-runs-per-hour", "42")
    page.fill("#opr-processing-reason", "Evening coverage")
    with page.expect_response(
        lambda response: "/ui/actions/admin.agent.processing" in response.url
        and response.request.method == "POST"
    ) as answered:
        page.click("[data-testid='admin-agent-processing-save']")
    response = answered.value
    assert response.status == 200, response.text()
    payload = response.json()
    assert payload["status"] == "accepted", payload
    assert payload["message"] == "The processing settings were saved."
    # The saved state is the one the server holds, not the state of the form.
    page.reload(wait_until="domcontentloaded")
    assert page.locator("input[name='keep_awake']").is_checked()
    assert page.locator("[data-testid='admin-processing-mode']").inner_text().strip() == (
        "Automatic processing"
    )
    assert page.locator("#opr-runs-per-hour").input_value() == "42"


def test_the_agent_processing_tab_fits_at_390(viewport_390, server, login) -> None:
    """The tab of the administration screen reads well on a phone."""
    page = viewport_390
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/admin?tab=agent_processing", wait_until="domcontentloaded")
    assert page.locator("[data-testid='admin-agent-processing']").is_visible()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("[data-testid='admin-processing-mode']"))
    assert_not_covered(page, page.locator("[data-testid='admin-agent-processing-save']"))


def test_the_operator_home_links_to_the_two_agents(page, server, login) -> None:
    """The agent status links of the home open the screen of the agent."""
    login("persona_agent_operator")
    page.goto(f"{server.base_url}/agents", wait_until="domcontentloaded")
    page.locator("[data-testid='agent-status-link'][data-agent-key='intake']").click()
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("h1").inner_text().strip() == "Intake agent"
    page.goto(f"{server.base_url}/agents", wait_until="domcontentloaded")
    page.locator("[data-testid='agent-status-link'][data-agent-key='adjudication']").click()
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("h1").inner_text().strip() == "Adjudication agent"


def test_the_operator_retries_the_failed_work(page, server, login) -> None:
    """The Retry button works the case again and the failure is gone.

    The case is archived while the operator is looking at the screen, so the
    run stops and the failure is recorded.  The case is restored, and the
    retry works it for real.
    """
    login("persona_agent_operator")
    application_id = _fail_a_case(page, server)
    # The failure is on the screen with a link to recorded attempt evidence.
    page.reload(wait_until="domcontentloaded")
    failure = page.locator("[data-testid='agent-failure-row']")
    assert failure.count() == 1
    assert "archived" in failure.first.inner_text()
    page.locator("[data-testid='agent-failure-detail-link']").click()
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("[data-testid='agent-run-detail']").is_visible()
    # The work stopped before an attempt was created, so the screen says so.
    assert page.locator("[data-testid='agent-run-detail-state']").inner_text().strip() == (
        "Failed"
    )
    assert "Not started" in page.locator(
        "[data-testid='agent-run-detail-provenance']"
    ).inner_text()
    button = page.locator("[data-testid='agent-run-detail-retry']")
    assert button.is_enabled()
    # The case is restored, so the retry can work on it.
    _set_case_status(server, application_id, "submitted")
    with page.expect_response(
        lambda answer: "/ui/actions/agent.retry" in answer.url
    ) as answered:
        button.click()
    payload = answered.value.json()
    assert payload["status"] == "accepted", payload
    assert payload["message"] == f"The intake agent ran again on {application_id}."
    # The work is done: the failure is gone and the case left the waiting list.
    page.locator("[data-testid='agent-run-detail-back']").click()
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("[data-testid='agent-run-history']").is_visible()
    page.goto(f"{server.base_url}/agent/intake", wait_until="domcontentloaded")
    assert page.locator("[data-testid='agent-failure-row']").count() == 0
    assert page.locator("[data-testid='agent-waiting-empty']").is_visible()
    assert_no_horizontal_overflow(page)


def test_the_agent_screen_retries_the_failed_work_and_opens_the_attempts(
    page, server, login
) -> None:
    """The Try again button and the history links of the agent screen work.

    The facts of the case are broken, so the classifier of the intake agent
    stops and the attempt is recorded as failed.  The facts are restored and
    the retry works the case for real, so the history of the agent holds
    both attempts of the case.
    """
    login("persona_agent_operator")
    response = page.request.post(
        f"{server.base_url}/api/intake/simulate",
        data=json.dumps({"scenario": "deck-high"}),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()
    _wake_the_agent(page, server, "intake")
    page.goto(f"{server.base_url}/agent/intake", wait_until="domcontentloaded")
    row = page.locator("[data-testid='agent-waiting-row']").first
    application_id = row.get_attribute("data-application-id")
    assert application_id
    # The classifier of the agent stops, so the attempt is recorded as failed.
    facts = _break_the_facts(server, application_id)
    with page.expect_response(
        lambda answer: "/ui/actions/agent.run.intake" in answer.url
    ) as answered:
        page.click("[data-testid='agent-run-one']")
    payload = answered.value.json()
    assert payload["status"] == "accepted", payload
    assert "stopped on" in payload["message"], payload
    page.reload(wait_until="domcontentloaded")
    assert page.locator("[data-testid='agent-failure-row']").count() == 1
    # The failure leads to the attempt that failed, not to an empty work view.
    page.locator("[data-testid='agent-failure-detail-link']").click()
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("[data-testid='agent-run-detail-state']").inner_text().strip() == (
        "Failed"
    )
    assert "Built in logic" in page.locator(
        "[data-testid='agent-run-detail-provenance']"
    ).inner_text()
    assert page.locator("[data-testid='agent-run-detail-revision']").inner_text().strip()
    # The facts are restored, so the retry can work on the case.
    _restore_the_facts(server, application_id, facts)
    page.goto(f"{server.base_url}/agent/intake", wait_until="domcontentloaded")
    with page.expect_response(
        lambda answer: "/ui/actions/agent.retry" in answer.url
    ) as answered:
        page.click("[data-testid='agent-retry']")
    payload = answered.value.json()
    assert payload["status"] == "accepted", payload
    assert payload["message"] == f"The intake agent ran again on {application_id}."
    page.reload(wait_until="domcontentloaded")
    # The work is done: the failure is gone and the case left the waiting list.
    assert page.locator("[data-testid='agent-failure-row']").count() == 0
    assert page.locator("[data-testid='agent-waiting-empty']").is_visible()
    # The history of the agent leads to the attempt that worked.
    page.locator("[data-testid='agent-history-detail-link']").first.click()
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("[data-testid='agent-run-detail']").is_visible()
    assert page.locator("[data-testid='agent-run-detail-state']").inner_text().strip() == (
        "Completed"
    )
    # The attempt that failed is the previous attempt of the same case.
    page.locator("[data-testid='agent-run-detail-previous']").click()
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("[data-testid='agent-run-detail-state']").inner_text().strip() == (
        "Failed"
    )
    # The later attempt replaced the failed one, and the screen says so.
    assert page.locator("[data-testid='agent-run-detail-replaced']").is_visible()
    page.locator("[data-testid='agent-run-detail-replaced-link']").click()
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("[data-testid='agent-run-detail-state']").inner_text().strip() == (
        "Completed"
    )
    # The run history of the operator leads to the same attempt.
    page.locator("[data-testid='agent-run-detail-back']").click()
    page.wait_for_load_state("domcontentloaded")
    page.locator("[data-testid='agent-run-detail-link']").first.click()
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("[data-testid='agent-run-detail']").is_visible()
    assert_no_horizontal_overflow(page)


def test_the_desktop_history_and_case_links_open_their_destinations(page, server, login) -> None:
    """Every history route leads to a usable operator screen on desktop."""
    login("persona_agent_operator")
    response = page.request.post(
        f"{server.base_url}/api/intake/simulate",
        data=json.dumps({"scenario": "deck-high"}),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()
    page.goto(f"{server.base_url}/agent/intake", wait_until="domcontentloaded")
    page.locator("[data-testid='agent-case-link']").first.click()
    assert page.locator("[data-testid='agent-case-summary']").is_visible()
    page.locator("[data-testid='agent-case-back']").click()
    assert page.locator("[data-testid='agent-run-history']").is_visible()
    _run_the_intake_agent(page, server)
    page.locator("[data-testid='agent-history-all']").click()
    selected = page.locator("[data-testid='run-filter-agent']")
    assert selected.input_value() == "intake"
    page.locator("[data-testid='agent-run-case-link']").first.click()
    assert page.locator("[data-testid='agent-case-summary']").is_visible()
    page.locator("[data-testid='agent-case-back']").click()
    assert page.locator("[data-testid='agent-run-history']").is_visible()
    page.get_by_role("link", name="Back to agents").click()
    assert page.locator("h1").inner_text().strip() == "Agents"


def test_the_desktop_status_refresh_only_reads_the_operator_status(page, server, login) -> None:
    """Refresh replaces status fragments and never starts agent processing.

    The refresh script reads the page again and puts the parts it read back
    in place.  The page is never left, so the marker of the page is still
    there after the refresh, and the values on the screen are the ones the
    server holds.
    """
    login("persona_agent_operator")
    page.goto(f"{server.base_url}/agents", wait_until="networkidle")
    assert page.locator("[data-testid='agent-operator-summary']").is_visible()
    # The page marks itself as one that must not be left.
    page.evaluate("() => { window.__noNav = 1; }")
    value = page.locator("[data-testid='agent-operator-summary'] .kpi .v").first
    original = value.inner_text().strip()
    # The value on the page is changed, so the test sees the difference
    # between the page and the server.
    value.evaluate("(node) => { node.textContent = '999'; }")
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and response.url.endswith("/agents")
        and response.request.resource_type == "fetch"
    ) as refreshed:
        page.locator("[data-testid='agent-status-refresh']").click()
    assert refreshed.value.status == 200
    # The page was not replaced: the marker of the page is still there.
    assert page.evaluate("() => window.__noNav") == 1
    # The values on the screen are the ones the server holds.
    assert value.inner_text().strip() == original
    assert page.locator("[data-testid='agent-operator-summary']").is_visible()
    assert page.recorded_errors == []


def test_the_agent_screen_refresh_reads_the_state_again_in_place(
    page, server, login
) -> None:
    """The Refresh link of an agent screen reads the state of the agent."""
    login("persona_agent_operator")
    page.goto(f"{server.base_url}/agent/intake", wait_until="networkidle")
    assert page.locator("[data-testid='agent-state']").is_visible()
    # The page marks itself as one that must not be left.
    page.evaluate("() => { window.__noNav = 1; }")
    mode = page.locator("[data-testid='agent-mode']")
    original = mode.inner_text().strip()
    assert original
    mode.evaluate("(node) => { node.textContent = '999'; }")
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and response.url.endswith("/agent/intake")
        and response.request.resource_type == "fetch"
    ) as refreshed:
        page.locator("[data-testid='agent-status-refresh']").click()
    assert refreshed.value.status == 200
    # The page was not replaced: the marker of the page is still there.
    assert page.evaluate("() => window.__noNav") == 1
    # The state on the screen is the one the server holds.
    assert mode.inner_text().strip() == original
    assert page.locator("[data-testid='agent-state']").is_visible()
    assert page.recorded_errors == []
