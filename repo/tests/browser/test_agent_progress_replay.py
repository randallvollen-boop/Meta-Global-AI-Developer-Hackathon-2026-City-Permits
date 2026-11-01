"""The replay of a recorded agent run on the screen of the operator.

The engine works a case in one request, so the steps of a run are complete
when the screen is read again.  The script replays them, level by level, and
settles on the states the run recorded.  A reader who asked for less motion
sees the recorded states at once and no spinner at all.
"""

from __future__ import annotations

import json

from conftest import BrowserServer

#: The script that watches the cards of the graph and records their states.
WATCH = """
() => {
  window.__states = [];
  const record = () => {
    document.querySelectorAll("[data-testid=agent-dag-node]").forEach((node) => {
      window.__states.push(node.getAttribute("data-state"));
    });
  };
  new MutationObserver(record).observe(document.body, {
    subtree: true,
    attributes: true,
    attributeFilter: ["data-state", "class"],
  });
}
"""


def _sign_in(page, server: BrowserServer, actor_id: str = "persona_agent_operator") -> None:
    """Open the picker of the personas and take one."""
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator(f'button[data-persona="{actor_id}"]').click()
    page.wait_for_url(f"{server.base_url}/agents*")


def _prepare(page, server: BrowserServer) -> None:
    """Let a case arrive and wake the intake agent."""
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


def _run_one(page, server: BrowserServer) -> None:
    """Work one waiting case and watch the cards of the graph."""
    page.evaluate(WATCH)
    with page.expect_response(
        lambda answer: "/ui/actions/agent.run.intake" in answer.url
    ) as answered:
        page.click("[data-testid='agent-run-one']")
    assert answered.value.json()["status"] == "accepted"


def test_the_run_replays_its_steps_and_settles_on_the_recorded_result(
    page, server: BrowserServer, login
) -> None:
    """The graph lights up level by level and ends on the recorded states."""
    login("persona_agent_operator")
    _prepare(page, server)
    _run_one(page, server)
    # The line above the graph says that the recorded steps are replayed.
    page.wait_for_function(
        "() => { const line = document.querySelector('[data-testid=agent-progress-status]');"
        " return line !== null && line.textContent.trim() === 'Replaying recorded steps'; }",
        timeout=15000,
    )
    # A card of the level that runs now shows the spinner.
    page.wait_for_selector("[data-testid='agent-dag-node'].running", timeout=15000)
    # The run buttons are off while the replay runs.
    assert page.locator("[data-testid='agent-run-all']").is_disabled()
    # The replay ends on the states the run recorded.
    page.wait_for_function(
        "() => { const block = document.querySelector('[data-run-progress]');"
        " return block !== null && block.getAttribute('data-replaying') === null; }",
        timeout=30000,
    )
    states = page.eval_on_selector_all(
        "[data-testid='agent-dag-node']",
        "nodes => nodes.map(node => node.getAttribute('data-state'))",
    )
    assert len(states) == 7
    assert "idle" not in states
    assert set(states) <= {"ok", "warn", "block"}
    # The steps ran in order: the cards waited and then ran.
    seen = page.evaluate("() => window.__states")
    assert "running" in seen
    assert "pending" in seen
    # The line above the graph names the recorded run again.
    line = page.locator("[data-testid='agent-progress-status']").inner_text().strip()
    assert line.startswith("Latest run: ")
    assert "7 of 7 steps" in line
    # The run buttons work again.
    assert page.locator("[data-testid='agent-run-all']").is_enabled()


def test_the_reduced_motion_path_shows_the_recorded_states_and_no_spinner(
    browser, server: BrowserServer
) -> None:
    """A reader who asked for less motion never sees a spinner."""
    context = browser.new_context(
        viewport={"width": 1280, "height": 900}, reduced_motion="reduce"
    )
    page = context.new_page()
    try:
        _sign_in(page, server)
        _prepare(page, server)
        _run_one(page, server)
        # The screen is read again with the run that was recorded.
        page.wait_for_function(
            "() => { const line = document.querySelector('[data-testid=agent-progress-status]');"
            " return line !== null && /Latest run: .*, 7 of 7 steps/.test(line.textContent); }",
            timeout=15000,
        )
        # No card ever showed a spinner and no card ever waited.
        seen = page.evaluate("() => window.__states")
        assert "running" not in seen
        assert "pending" not in seen
        assert page.locator("[data-testid='agent-dag-node'].running").count() == 0
        # The recorded states are on the screen all the same.
        states = page.eval_on_selector_all(
            "[data-testid='agent-dag-node']",
            "nodes => nodes.map(node => node.getAttribute('data-state'))",
        )
        assert len(states) == 7
        assert "idle" not in states
    finally:
        context.close()
