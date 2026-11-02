"""The operator can see how many cases wait and which ones a press handled."""

from __future__ import annotations

import json
import re

from playwright.sync_api import expect

from conftest import BrowserServer


def _arrive(page, server: BrowserServer, scenario: str) -> None:
    response = page.request.post(
        f"{server.base_url}/api/intake/simulate",
        data=json.dumps({"scenario": scenario}),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()


def _wake(page, server: BrowserServer, agent_key: str) -> None:
    page.goto(f"{server.base_url}/agent/{agent_key}", wait_until="domcontentloaded")
    with page.expect_response(lambda answer: "/ui/actions/agent.toggle" in answer.url):
        page.click("[data-testid='agent-toggle']")
    expect(page.locator("[data-testid='agent-mode']")).to_have_text("awake")


def _settle(page) -> None:
    """Wait until the recorded steps have finished replaying."""
    page.wait_for_function(
        "() => { const block = document.querySelector('[data-run-progress]');"
        " return block !== null && block.getAttribute('data-replaying') === null; }",
        timeout=30000,
    )


def _assert_empty(page) -> None:
    button = page.locator("[data-testid='agent-run-all']")
    expect(page.locator("#agent-waiting-heading")).to_have_text("Waiting work (0)")
    assert button.is_disabled()
    assert button.get_attribute("aria-describedby") == "agent-nothing-waiting"
    expect(page.locator("[data-testid='agent-nothing-waiting']")).to_have_text(
        "Nothing is waiting"
    )


def _assert_last_run(page, agent_key: str, count: int) -> None:
    items = page.locator("[data-testid='agent-last-run-item']")
    assert items.count() == count
    summary = page.locator("[data-testid='agent-last-run-summary']").inner_text()
    noun = "case" if count == 1 else "cases"
    assert f"{count} {noun}" in summary
    assert " by " in summary
    for index in range(count):
        link = items.nth(index).locator("[data-testid='agent-last-run-link']")
        outcome = items.nth(index).locator("[data-testid='agent-last-run-outcome']")
        reference = link.inner_text().strip()
        assert re.fullmatch(r"SYN-APP-\d+", reference), reference
        assert not reference.startswith("app_")
        words = outcome.inner_text().strip()
        assert words
        assert "finding(s)" not in words
        assert "The recommendation is pending" not in words
        href = link.get_attribute("href") or ""
        assert f"?from=/agent/{agent_key}" in href
        assert "/agents/cases/" in href


def test_intake_shows_the_count_the_button_and_the_cases_of_the_run(
    page, server: BrowserServer, login
) -> None:
    """A press of two cases lists each one, and the next press has nothing to do."""
    login("persona_agent_operator")
    _arrive(page, server, "deck-high")
    _arrive(page, server, "address-unknown")
    page.goto(f"{server.base_url}/agent/intake", wait_until="domcontentloaded")
    expect(page.locator("#agent-waiting-heading")).to_have_text("Waiting work (2)")
    button = page.locator("[data-testid='agent-run-all']")
    assert button.inner_text().strip() == "Process 2 cases"
    assert button.is_disabled()
    _wake(page, server, "intake")
    button = page.locator("[data-testid='agent-run-all']")
    assert button.is_enabled()
    assert button.inner_text().strip() == "Process 2 cases"
    with page.expect_response(
        lambda answer: "/ui/actions/agent.run.intake" in answer.url
    ) as answered:
        button.click()
    payload = answered.value.json()
    assert payload["status"] == "accepted", payload
    assert payload["message"] == "The intake agent ran on 2 waiting case(s)."
    page.wait_for_selector("[data-testid='agent-last-run-item']")
    _settle(page)
    _assert_last_run(page, "intake", 2)
    outcomes = [
        page.locator("[data-testid='agent-last-run-outcome']").nth(index).inner_text()
        for index in range(2)
    ]
    assert any("Ready for review" in outcome for outcome in outcomes)
    assert any(outcome.startswith("Routed to early resolution:") for outcome in outcomes)
    _assert_empty(page)
    page.locator("[data-testid='agent-last-run-link']").first.click()
    page.wait_for_load_state("domcontentloaded")
    back = page.locator("[data-testid='agent-case-back']")
    expect(back).to_have_text("Back to the agent")
    assert "/agent/intake" in (back.get_attribute("href") or "")
    back.click()
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator("#agent-waiting-heading")).to_have_text("Waiting work (0)")
    assert page.recorded_errors == []


def test_adjudication_shows_the_count_the_button_and_the_case_of_the_run(
    page, server: BrowserServer, login
) -> None:
    """The adjudication screen follows the same count, button and last-run pattern."""
    login("persona_agent_operator")
    _arrive(page, server, "deck-high")
    _wake(page, server, "intake")
    with page.expect_response(lambda answer: "/ui/actions/agent.run.intake" in answer.url):
        page.click("[data-testid='agent-run-all']")
    _wake(page, server, "adjudication")
    expect(page.locator("#agent-waiting-heading")).to_have_text("Waiting work (1)")
    button = page.locator("[data-testid='agent-run-all']")
    assert button.is_enabled()
    assert button.inner_text().strip() == "Process 1 case"
    with page.expect_response(
        lambda answer: "/ui/actions/agent.run.adjudication" in answer.url
    ) as answered:
        button.click()
    payload = answered.value.json()
    assert payload["status"] == "accepted", payload
    assert payload["message"] == "The adjudication agent ran on 1 case(s)."
    page.wait_for_selector("[data-testid='agent-last-run-item']")
    _settle(page)
    _assert_last_run(page, "adjudication", 1)
    _assert_empty(page)
    page.locator("[data-testid='agent-last-run-link']").click()
    page.wait_for_load_state("domcontentloaded")
    back = page.locator("[data-testid='agent-case-back']")
    expect(back).to_have_text("Back to the agent")
    assert "/agent/adjudication" in (back.get_attribute("href") or "")
    back.click()
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator("[data-testid='agent-last-run']")).to_be_visible()
    assert page.recorded_errors == []
