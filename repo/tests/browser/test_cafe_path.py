"""The café path runs from the first link to the public record.

The journey of one permit: the Data Steward accepts the link the assistant
recommends, the Agent Operator lets the agent route the case, the Permit
Reviewer runs the checks and approves it, the City Administrator assesses the
fee and matches the receipt from the old finance account, the Permit Reviewer
issues the permit and the resident finds it on the public record.

Every step goes through a real form of the interface, the way a judge
follows the written walkthrough.  The records are fictional.
"""
# REQUIRES: UX-04, PER-01, PER-04, PER-05, FIN-01, FIN-04, FIN-05, MDM-02
# The café path is the chain of one permit, from the link to the public record.

from __future__ import annotations

import re

from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.session import SessionFactory, transaction
from conftest import BrowserServer

#: The case of the café, the one the walkthrough names.
CASE_ID = "app_synth_001"

#: The receipt of the fee, paid from the old finance account of the café.
RECEIPT_ID = "payment_d01_settled"

#: The source record of the permit account of the café.
ACCOUNT_RECORD = "PER-AP-0003"

#: The source record of the contractor of the café.
CONTRACTOR_RECORD = "PER-CR-00188"


def prepare_queue(server: BrowserServer) -> None:
    """Put the Cedarline tasks in the queue of the demonstration."""
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            seed_cedarline(session)
    finally:
        factory.dispose()


def click_action(page, testid: str, action_id: str) -> str:
    """Click a button of the interface and return the message it answered with."""
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


def wake_the_intake_agent(page, server: BrowserServer, login) -> None:
    """Wake the intake agent, the way the Agent Operator does."""
    login("persona_agent_operator")
    page.goto(f"{server.base_url}/agent/intake", wait_until="load")
    page.wait_for_selector('[data-testid="agent-toggle"]')
    if page.locator('[data-testid="agent-mode"]').inner_text().strip() == "asleep":
        page.locator('[data-testid="agent-toggle"]').click()
        page.wait_for_function(
            "() => document.querySelector('[data-testid=agent-mode]')"
            "?.textContent.trim() === 'awake'"
        )
    assert page.locator('[data-testid="agent-mode"]').inner_text().strip() == "awake"


def accept_the_recommendation(page, server: BrowserServer, record: str) -> None:
    """Let the Data Steward accept the recommendation of the assistant."""
    page.goto(f"{server.base_url}/steward?filter=needs_review", wait_until="load")
    row = page.locator(f'[data-issue-row]:has-text("{record}")').first
    assert row.count() == 1, f"the queue holds no task of {record}"
    row.locator('[data-testid="issue-link"]').click()
    page.wait_for_selector('[data-testid="assistant-accept"]')
    reason = page.locator('[data-testid="assistant-reason-field"]')
    reason.fill("the source names this master record and no other fits as well")
    message = click_action(page, "assistant-accept", "steward.assist.accept")
    assert "accepted" in message.lower()


def start_the_copy(page, server: BrowserServer) -> str:
    """Press Start fresh and return the reference of the copy."""
    page.goto(f"{server.base_url}/walkthrough", wait_until="domcontentloaded")
    with page.expect_response(
        lambda response: "/walkthrough/start-fresh" in response.url
    ) as posted:
        page.locator(
            '[data-testid="walkthrough-path"][data-path="cafe"] [data-testid="path-fresh"]'
        ).click()
    assert posted.value.status == 303
    page.wait_for_url(re.compile(r"/walkthrough\?case=app_judge_"))
    notice = page.locator('[data-testid="judge-copy-notice"]')
    notice.wait_for()
    match = re.search(r"CAFE-2026-[A-Z0-9]+", notice.inner_text())
    assert match is not None, notice.inner_text()
    return match.group(0)


def test_the_café_path_runs_on_the_copy_of_the_judge(
    page, server: BrowserServer, login, submit_action
) -> None:
    """The whole path on the copy the judge made: the agent routes it too."""
    reference = start_the_copy(page, server)

    # 1. The Agent Operator wakes the agents and lets the agent route the case.
    wake_the_assistant(page, server, login)
    wake_the_intake_agent(page, server, login)
    page.goto(f"{server.base_url}/agent/intake", wait_until="load")
    row = page.locator(f'[data-testid="agent-waiting-row"]:has-text("{reference}")')
    assert row.count() == 1, "the agent waits for the copy of the café"
    with page.expect_response(
        lambda response: "/ui/actions/agent.run.intake" in response.url
    ) as posted:
        row.locator('[data-testid="agent-run-one"]').click()
    assert posted.value.status == 200, posted.value.text()
    assert posted.value.json()["status"] == "accepted"

    # The case of the copy waits for the reviewer now.
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/queue/review", wait_until="domcontentloaded")
    assert page.locator(f'[data-testid="review-row"]:has-text("{reference}")').count() == 1

    # 2. The Data Steward accepts the links the assistant recommends.
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward?filter=needs_review", wait_until="load")
    message = click_action(page, "assistant-prepare", "steward.assist.prepare")
    assert "recommendation" in message
    page.wait_for_selector('[data-testid="recommendation-pill"]')
    rows = page.locator('[data-issue-row][data-recommendation="high"]')
    assert rows.count() == 3, "the copy of the café holds three owner records"
    for _ in range(3):
        row = rows.first
        row.locator('[data-testid="issue-link"]').click()
        page.wait_for_selector('[data-testid="assistant-accept"]')
        reason = page.locator('[data-testid="assistant-reason-field"]')
        reason.fill("the source names this master record and no other fits as well")
        message = click_action(page, "assistant-accept", "steward.assist.accept")
        assert "accepted" in message.lower()
        page.goto(f"{server.base_url}/steward?filter=needs_review", wait_until="load")
        page.wait_for_selector('[data-testid="recommendation-pill"]')

    # The property of the café waits for the steward as well.
    property_row = page.locator('[data-issue-row][data-kind="parcel"]').first
    assert property_row.count() == 1, "the property of the café waits for the steward"
    property_row.locator('[data-testid="issue-link"]').click()
    page.wait_for_selector('[data-action-id="parcel.link.decide"]')
    message = submit_action(
        "parcel.link.decide",
        {"reason": "the locator names this parcel for the address of the café"},
    )
    assert "parcel" in message.lower()

    # 3. The Permit Reviewer runs the checks and approves the copy.
    cafe_steps = page.request.get(f"{server.base_url}/tour/steps?path=cafe").json()["steps"]
    copy_id = next(
        step["path"] for step in cafe_steps if "/permits/" in step["path"]
    ).rsplit("/", 1)[-1]
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/{copy_id}", wait_until="domcontentloaded")
    page.locator('[data-testid="workspace-tab"][data-tab="people"]').click()
    message = submit_action(
        "parcel.confirm",
        {"application_id": copy_id, "reason": "the parcel is the one of the address"},
    )
    assert "parcel" in message.lower()
    page.reload(wait_until="domcontentloaded")
    message = submit_action("permit.evaluate", {"application_id": copy_id})
    assert "Validation finished" in message
    page.reload(wait_until="domcontentloaded")
    assert "Passed" in page.locator('[data-testid="rule-results"]').inner_text()

    message = submit_action(
        "permit.decide",
        {
            "application_id": copy_id,
            "outcome": "approved",
            "reason": "the validated inputs and the approved links support the application",
        },
    )
    assert "Recorded the reviewer decision" in message

    # 4. The City Administrator assesses the fee and matches the receipt.
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/reconciliation", wait_until="domcontentloaded")
    message = submit_action(
        "finance.assess",
        {
            "application_id": reference,
            "valuation": "50000.00",
            "reason": "the declared valuation of the application",
        },
    )
    assert "Assessed" in message
    page.reload(wait_until="domcontentloaded")
    row = page.locator(f'[data-testid="assessment-row"][data-application-id="{copy_id}"]').first
    assessment_id = row.get_attribute("data-assessment-id")
    assert assessment_id
    assert "150.00" in row.inner_text()

    page.goto(f"{server.base_url}/reconciliation?tab=receipts", wait_until="domcontentloaded")
    receipt = page.locator('[data-testid="payment-row"]:has-text("ERP-TXN-J")').first
    assert receipt.count() == 1, "the receipt of the copy is on the register"
    receipt_id = receipt.locator("td").first.inner_text().strip()
    page.goto(f"{server.base_url}/reconciliation", wait_until="domcontentloaded")

    message = submit_action(
        "finance.allocate",
        {
            "payment_id": receipt_id,
            "assessment_id": assessment_id,
            "amount": "150.00",
            "currency": "USD",
            "idempotency_key": "cafe-copy-allocation-1",
            "reason": "the settled receipt from the old finance account covers the fee",
        },
    )
    assert "Confirmed an allocation" in message
    message = submit_action(
        "finance.reconcile",
        {
            "assessment_id": assessment_id,
            "payment_ids": receipt_id,
        },
    )
    assert "Reconciled position" in message

    # 5. The Permit Reviewer issues the permit of the copy.
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/{copy_id}", wait_until="domcontentloaded")
    message = submit_action(
        "permit.issue",
        {
            "application_id": copy_id,
            "command_key": "cafe-copy-issue-1",
            "reason": "the finance position is exact",
        },
    )
    assert "Issued the simulated permit" in message
    permit_number = re.search(r"ACME-2026-\d+", message)
    assert permit_number is not None

    # 6. The resident finds the permit on the public record.
    page.goto(f"{server.base_url}/city/community", wait_until="domcontentloaded")
    page.locator('[data-testid="community-q"]').fill(permit_number.group(0))
    page.locator('[data-testid="community-search"]').click()
    page.wait_for_selector('[data-testid="community-results"]')
    assert permit_number.group(0) in page.locator(
        '[data-testid="community-results"]'
    ).inner_text()
    assert page.recorded_errors == []


def test_the_café_path_runs_from_the_link_to_the_public_record(
    page, server: BrowserServer, login, submit_action
) -> None:
    """The whole chain of the café, one form at a time."""
    prepare_queue(server)
    wake_the_assistant(page, server, login)

    # 1. The Data Steward accepts the link the assistant recommends.
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward?filter=needs_review", wait_until="load")
    message = click_action(page, "assistant-prepare", "steward.assist.prepare")
    assert "recommendation" in message
    accept_the_recommendation(page, server, ACCOUNT_RECORD)

    # The contractor of the café is linked the same way.
    page.goto(f"{server.base_url}/steward", wait_until="domcontentloaded")
    submit_action(
        "registry.propose",
        {
            "source_system_id": "permitting",
            "dataset_key": "contractor_register",
            "source_record_id": CONTRACTOR_RECORD,
        },
    )
    message = submit_action(
        "registry.decide",
        {
            "source_system_id": "permitting",
            "dataset_key": "contractor_register",
            "source_record_id": CONTRACTOR_RECORD,
            "entity_id": "party_ironvale",
            "decision": "approve",
            "reason": "the registration and the declared contractor agree",
        },
    )
    assert "Recorded the approve decision" in message

    # 2. The Agent Operator lets the agent route the case.
    wake_the_intake_agent(page, server, login)

    # 3. The Permit Reviewer runs the checks and approves the case.
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/{CASE_ID}", wait_until="domcontentloaded")
    message = submit_action("permit.evaluate", {"application_id": CASE_ID})
    assert "Validation finished" in message
    page.reload(wait_until="domcontentloaded")
    assert page.locator('[data-testid="rule-results"]').count() == 1
    assert "Passed" in page.locator('[data-testid="rule-results"]').inner_text()

    message = submit_action(
        "permit.decide",
        {
            "application_id": CASE_ID,
            "outcome": "approved",
            "reason": "the validated inputs and the approved links support the application",
        },
    )
    assert "Recorded the reviewer decision" in message
    page.reload(wait_until="domcontentloaded")
    page.locator('[data-testid="decision-history"] > summary').click()
    assert "approved" in page.locator('[data-testid="decision-table"]').inner_text()

    # 4. The City Administrator assesses the fee and matches the receipt.
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/reconciliation", wait_until="domcontentloaded")
    message = submit_action(
        "finance.assess",
        {
            "application_id": CASE_ID,
            "valuation": "50000.00",
            "reason": "the declared valuation of the application",
        },
    )
    assert "Assessed" in message
    page.reload(wait_until="domcontentloaded")
    row = page.locator(f'[data-testid="assessment-row"][data-application-id="{CASE_ID}"]').first
    assessment_id = row.get_attribute("data-assessment-id")
    assert assessment_id
    assert "150.00" in row.inner_text()

    message = submit_action(
        "finance.allocate",
        {
            "payment_id": RECEIPT_ID,
            "assessment_id": assessment_id,
            "amount": "150.00",
            "currency": "USD",
            "idempotency_key": "cafe-path-allocation-1",
            "reason": "the settled receipt from the old finance account covers the fee",
        },
    )
    assert "Confirmed an allocation" in message

    message = submit_action(
        "finance.reconcile",
        {
            "assessment_id": assessment_id,
            "payment_ids": RECEIPT_ID,
        },
    )
    assert "Reconciled position" in message
    page.reload(wait_until="domcontentloaded")
    row = page.locator(f'[data-testid="assessment-row"][data-application-id="{CASE_ID}"]').first
    assert "0.00" in row.inner_text()
    assert row.get_attribute("data-status") in {"reconciled", "closed", "exact"}

    # 5. The Permit Reviewer issues the permit.
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/{CASE_ID}", wait_until="domcontentloaded")
    message = submit_action(
        "permit.issue",
        {
            "application_id": CASE_ID,
            "command_key": "cafe-path-issue-1",
            "reason": "the finance position is exact",
        },
    )
    assert "Issued the simulated permit" in message
    permit_number = re.search(r"ACME-2026-\d+", message)
    assert permit_number is not None

    # 6. The resident finds the permit on the public record.
    page.goto(f"{server.base_url}/city/community", wait_until="domcontentloaded")
    page.locator('[data-testid="community-q"]').fill(permit_number.group(0))
    page.locator('[data-testid="community-search"]').click()
    page.wait_for_selector('[data-testid="community-results"]')
    results = page.locator('[data-testid="community-results"]').inner_text()
    assert permit_number.group(0) in results
    assert page.recorded_errors == []
