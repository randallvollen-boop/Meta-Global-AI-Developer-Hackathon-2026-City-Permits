"""The plain reason of a recommendation in a real browser.

A 6 ft front fence is denied, and the agent case page and the review queue say
why in words: the rule by its title, the submitted value against the limit and
the citation, and never a bare rule id.
"""

from __future__ import annotations

import json

from conftest import BrowserServer

TITLE = "Fence height, front yard"
REASON = (
    "Recommend deny: the front yard fence is 6 ft; the limit is 4 ft "
    f"(ACME Code §14-305, {TITLE})."
)


def _toggle_and_run(page, server: BrowserServer, agent: str, run_action: str) -> None:
    page.goto(f"{server.base_url}/agent/{agent}", wait_until="domcontentloaded")
    with page.expect_response(lambda a: "/ui/actions/agent.toggle" in a.url) as answered:
        page.click("[data-testid='agent-toggle']")
    assert answered.value.json()["status"] == "accepted"
    page.reload(wait_until="domcontentloaded")
    with page.expect_response(lambda a: run_action in a.url) as answered:
        page.click("[data-testid='agent-run-all']")
    assert answered.value.json()["status"] == "accepted"


def test_a_denied_front_fence_says_why_on_the_case_page_and_the_queue(
    page, server: BrowserServer, login
) -> None:
    login("persona_agent_operator")
    response = page.request.post(
        f"{server.base_url}/api/intake/simulate",
        data=json.dumps({"scenario": "fence-front-too-tall"}),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()
    application_id = response.json()["results"][0]["application_id"]
    _toggle_and_run(page, server, "intake", "/ui/actions/agent.run.intake")
    _toggle_and_run(page, server, "adjudication", "/ui/actions/agent.run.adjudication")

    # The agent case page leads with the outcome and the reason in words.
    page.goto(f"{server.base_url}/agents/cases/{application_id}", wait_until="domcontentloaded")
    assert page.locator('[data-testid="agent-case-recommendation-outcome"]').inner_text() == "Deny"
    reason = page.locator('[data-testid="agent-case-recommendation-reason"]').inner_text()
    assert reason == REASON
    assert "4 ft or lower, or a variance" in page.locator(
        '[data-testid="agent-case-recommendation-more-reasons"]'
    ).inner_text()
    assert "DF-1" not in page.locator('[data-testid="agent-case-recommendation"]').inner_text()

    # The waiting list of the agent screen says the same in its short form.
    page.goto(f"{server.base_url}/agent/adjudication", wait_until="domcontentloaded")
    assert page.locator('[data-testid="agent-awaiting-reason"]').first.inner_text() == REASON

    # The review queue shows the first reason, and the rest under More details.
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/queue/review", wait_until="domcontentloaded")
    cell = page.locator('[data-testid="review-recommendation-reason"]').first
    assert cell.inner_text() == REASON
    assert "DF-1" not in page.locator('[data-testid="review-row"]').first.inner_text()
    page.locator('[data-testid="review-row-more"] summary').first.click()
    assert "or a variance" in page.locator(
        '[data-testid="review-recommendation-more-reasons"]'
    ).first.inner_text()

    # The permit workspace shows the same reason.
    page.goto(f"{server.base_url}/permits/{application_id}", wait_until="domcontentloaded")
    assert page.locator('[data-testid="recommendation-reason"]').inner_text() == REASON
    assert "DF-1" not in page.locator('[data-testid="agent-recommendation"]').inner_text()
    assert page.recorded_errors == []
