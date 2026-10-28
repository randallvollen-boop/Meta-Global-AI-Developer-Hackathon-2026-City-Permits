"""The single-administrator click path in the browser, with one persona.

City Administrator: What-if, the fence 7 ft scenario, Run what-if, Save as a
draft rule change, open the draft, submit it for review, Approve (with a
confirmation and a reason), Publish.  The whole path uses the one City
Administrator persona; no second administrator account exists in the demo.
"""
# REQUIRES: REF-02, UX-01, UX-02, PER-04

from __future__ import annotations

import pytest
from conftest import BrowserServer


@pytest.fixture(autouse=True)
def single_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the single policy so the path never depends on the machine environment.

    The server subprocess inherits the environment, so this is set before it starts.
    """
    monkeypatch.setenv("ACME_APPROVAL_POLICY", "single")


def overflow(page) -> int:
    return page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")


def act(page, action_id: str, *, reason: str, confirm: bool = False, precedence: str = "") -> None:
    """Open one action card of the selected version, fill it and submit it."""
    details = page.locator(f'details[data-action-id="{action_id}"]').first
    form = details.locator("form.action-form")
    if not form.is_visible():
        details.locator("summary").click()
    form.locator('[name="reason"]').fill(reason)
    if confirm:
        form.locator('[name="confirm_author_approval"]').check()
    if precedence:
        form.locator('[name="precedence"]').fill(precedence)
    with page.expect_response(
        lambda response: "/ui/actions/" in response.url and response.request.method == "POST"
    ) as answered:
        form.locator('button[type="submit"]').click()
    assert answered.value.status == 200, answered.value.text()


def test_one_administrator_takes_the_fence_change_from_what_if_to_published(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    page.set_viewport_size({"width": 1280, "height": 900})

    # What-if, the fence 7 ft scenario, Run what-if.
    page.goto(f"{server.base_url}/policy/scenarios", wait_until="domcontentloaded")
    page.locator('[data-testid="policy-suggestion"]').first.click()
    page.wait_for_url("**/policy/scenarios/polscen_*")
    page.locator('[data-testid="policy-run-count"], #run-count').first.fill("200")
    page.locator('[data-testid="policy-run-submit"]').click()
    page.wait_for_url("**/policy/runs/polrun_*")

    # Save as a draft rule change: the label says it is ready for the administrator's approval.
    page.locator('[data-testid="policy-draft-submit"]').click()
    page.wait_for_selector('[data-testid="policy-draft-status"]')
    assert "Draft: ready for your approval" in page.locator(
        '[data-testid="policy-draft-state"]'
    ).first.inner_text()
    assert "Draft: needs independent approval" not in page.content()
    assert page.locator('[data-testid="policy-draft-approve"]').count() == 0

    # Open the draft.
    page.locator('[data-testid="policy-draft-open"]').first.click()
    page.wait_for_selector('[data-testid="selected-version"]')
    assert page.locator('[data-testid="approval-policy"]').inner_text().startswith(
        "Approval policy: single administrator"
    )
    version_url = page.url
    assert overflow(page) <= 1

    # Submit for review, then approve with a reason and an explicit confirmation.
    act(page, "rule.submit", reason="Ready for review.")
    page.goto(version_url, wait_until="domcontentloaded")
    next_action = page.locator('[data-testid="selected-version-next-action"]').inner_text()
    assert "Approve version" in next_action
    assert "You authored this version" not in page.content()

    approve = page.locator('details[data-action-id="rule.approve"]').first
    approve.locator("summary").click()
    form = approve.locator("form.action-form")
    # The confirmation and the reason are both required; the form says so.
    assert form.locator('[name="confirm_author_approval"]').get_attribute("required") is not None
    assert form.locator('[name="reason"]').get_attribute("required") is not None
    act(
        page,
        "rule.approve",
        reason="Agreed in the fictional planning session.",
        confirm=True,
    )
    page.goto(version_url, wait_until="domcontentloaded")
    approval = page.locator('[data-testid="selected-version-states"]').inner_text()
    assert "Approved by the author (single-administrator policy)" in approval
    history = page.locator('[data-testid="selected-version-history"]').inner_text()
    assert "Approved by the author (single-administrator policy)" in history
    assert "Agreed in the fictional planning session." in history

    # Publish. A published fence limit already exists, so the publication names its precedence.
    act(
        page,
        "rule.publish",
        reason="Fictional publication.",
        precedence="Replaces the earlier fence limit",
    )
    page.goto(version_url, wait_until="domcontentloaded")
    assert "published" in page.locator('[data-testid="selected-version"] .badge').first.inner_text().lower()
    history = page.locator('[data-testid="selected-version-history"]').inner_text()
    assert "Published by the author (single-administrator policy)" in history

    # The overview shows the active policy on the Proposed changes card.
    page.goto(f"{server.base_url}/overview", wait_until="domcontentloaded")
    assert "Approval policy: single administrator" in page.locator(
        '[data-testid="overview-approval-policy"]'
    ).inner_text()
    assert page.recorded_errors == []
