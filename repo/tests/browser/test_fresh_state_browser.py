"""The state of the screen after an action: the page shows the stored state.

An action is sent in the background, so the page has to read itself again
from the server.  These tests walk the sequences a person walks and read the
screen without a manual reload.
"""

from __future__ import annotations

import json

from playwright.sync_api import expect

#: The seeded demonstration case.
CASE = "app_synth_001"

#: The reference the City uses for that case everywhere else.
CASE_REFERENCE = "SYN-APP-001"


def _simulate(page, server, scenario: str) -> str:
    """Let one synthetic case arrive from outside the City and return its id."""
    response = page.request.post(
        f"{server.base_url}/api/intake/simulate",
        data=json.dumps({"scenario": scenario}),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()
    (result,) = response.json()["results"]
    return str(result["application_id"])


def _run_the_intake_agent(page, server) -> None:
    """Wake the intake agent and let it work the waiting case.

    The address locator runs with the agent, so the case gets a parcel link
    the Data Steward has to approve.
    """
    page.goto(f"{server.base_url}/agent/intake", wait_until="domcontentloaded")
    with page.expect_response(lambda answer: "/ui/actions/agent.toggle" in answer.url):
        page.click("[data-testid='agent-toggle']")
    expect(page.locator("[data-testid='agent-mode']")).to_have_text("awake")
    with page.expect_response(lambda answer: "/ui/actions/agent.run.intake" in answer.url):
        page.click("[data-testid='agent-run-all']")
    expect(page.locator("[data-testid='agent-waiting-empty']")).to_be_visible()


def test_waking_the_agent_shows_the_awake_agent_without_a_reload(page, server, login) -> None:
    """The state of the agent on the screen is the state the server holds.

    A person must not have to reload to see that the agent is awake, and the
    same holds for putting it back to sleep.
    """
    login("persona_agent_operator")
    for agent_key in ("intake", "adjudication"):
        page.goto(f"{server.base_url}/agent/{agent_key}", wait_until="domcontentloaded")
        mode = page.locator("[data-testid='agent-mode']")
        toggle = page.locator("[data-testid='agent-toggle']")
        assert mode.inner_text().strip() == "asleep"
        assert toggle.inner_text().strip() == "Wake agent"
        with page.expect_response(lambda answer: "/ui/actions/agent.toggle" in answer.url) as answered:
            toggle.click()
        assert answered.value.json()["status"] == "accepted"
        # The page reads itself again: the agent is awake without a reload.
        expect(mode).to_have_text("awake")
        expect(toggle).to_have_text("Put agent to sleep")
        assert page.locator("[data-testid='agent-sleep-notice']").count() == 0
        assert page.locator("[data-testid='agent-run-all']").is_enabled()
        if agent_key == "intake":
            # The sidebar of the screen names the state the server holds too.
            expect(page.locator("[data-testid='agent-status']")).to_contain_text("awake")
        # The same holds for putting the agent back to sleep.
        with page.expect_response(lambda answer: "/ui/actions/agent.toggle" in answer.url) as answered:
            toggle.click()
        assert answered.value.json()["status"] == "accepted"
        expect(mode).to_have_text("asleep")
        expect(toggle).to_have_text("Wake agent")
        assert page.locator("[data-testid='agent-sleep-notice']").count() == 1
        assert page.locator("[data-testid='agent-run-all']").is_disabled()
    assert page.recorded_errors == []


def test_the_case_shows_the_stored_state_after_the_checks(
    page, server, login, submit_action
) -> None:
    """Confirming the parcel and running the checks shows the stored state.

    The blocker panel and the decision form are read from the database, so
    they are current as soon as the action is accepted: the reviewer never
    has to reload to see that the case is ready for a decision.
    """
    # A case arrives with a typed address the locator matched to a parcel.
    login("persona_agent_operator")
    application_id = _simulate(page, server, "address-typo")
    _run_the_intake_agent(page, server)

    # The Data Steward approves the identity link and the parcel link.
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="domcontentloaded")
    page.locator('tr[data-kind="link"] a[data-testid="issue-link"]').first.click()
    page.wait_for_load_state("domcontentloaded")
    submit_action(
        "registry.decide",
        {"reason": "the recorded alias and the declared reference name the same party"},
    )
    page.goto(
        f"{server.base_url}/steward/issues/parcel/{application_id}", wait_until="domcontentloaded"
    )
    submit_action(
        "parcel.link.decide",
        {"reason": "the typed address is on the parcel the locator found"},
    )

    # The reviewer opens the case: one blocker is left, the parcel.
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/{application_id}", wait_until="domcontentloaded")
    expect(page.locator("[data-testid='checks-summary']")).to_contain_text("1 blocker")
    assert page.locator("[data-testid='decision-form']").count() == 0

    # Confirming the parcel clears the blocker without a reload.
    page.locator("#tab-people").click()
    submit_action("parcel.confirm", {"reason": "this is the right property"})
    page.locator("#tab-review").click()
    expect(page.locator("[data-testid='checks-summary']")).to_have_count(0)
    expect(page.locator("[data-testid='blockers-empty']")).to_be_visible()

    # Running the application checks brings the decision form, without a reload.
    submit_action("permit.evaluate", {})
    expect(page.locator("[data-testid='decision-form']")).to_have_count(1)
    expect(page.locator("[data-testid='decision-form']")).to_contain_text(
        "Record review decision"
    )
    expect(page.locator("[data-testid='rule-results']")).to_be_visible()
    assert page.recorded_errors == []


def test_the_audit_log_names_the_case_by_its_reference(page, server, login, submit_action) -> None:
    """The audit log names a case by the reference the City uses elsewhere.

    The internal identifier stays in the link that opens the case; it is not
    shown as the name of the record.
    """
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/{CASE}", wait_until="domcontentloaded")
    submit_action("permit.evaluate", {"application_id": CASE})

    login("persona_city_administrator")
    page.goto(
        f"{server.base_url}/ops/audit?search={CASE}", wait_until="domcontentloaded"
    )
    record = page.locator("[data-testid='audit-record-link']").first
    expect(record).to_have_text(CASE_REFERENCE)
    # The internal identifier stays in the link that opens the case.
    expect(record).to_have_attribute("href", f"/permits/{CASE}")
    # The detail of the event names the case by its reference too.
    page.locator("[data-testid='audit-row']").first.locator(
        "[data-testid='ui-detail-link']"
    ).click()
    drawer = page.locator("#ui-drawer")
    drawer.wait_for(state="visible")
    expect(drawer).to_contain_text(CASE_REFERENCE)
    assert CASE not in drawer.inner_text()
    assert page.recorded_errors == []
