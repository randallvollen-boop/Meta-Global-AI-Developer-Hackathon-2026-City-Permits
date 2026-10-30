"""The automatic linking settings of the Data Steward in a browser.

The screen reports the mode the automation really runs in, the thresholds of
the policy, a preview of the accepted source records and the two controls
that change the policy.  The tests walk the screen as the Data Steward on a
desktop, and they check that the screen still fits a phone.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02, UX-04, SEC-01
# The Data Steward reads the settings, previews the policy, activates it with
# a reason and pauses it with a reason.  Every control does what it says.

from __future__ import annotations

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

#: The reason the steward gives when a policy is activated.
ACTIVATE_REASON = "The applicant records wait for a master record."

#: The reason the steward gives when the automation is paused.
PAUSE_REASON = "The steward reads the first results before the work continues."


def test_the_settings_screen_says_the_automation_is_paused(
    page, server: BrowserServer, login
) -> None:
    """The default page says that automatic linking is paused."""
    login("persona_data_steward")
    response = page.goto(f"{server.base_url}/steward/automation", wait_until="load")
    assert response is not None
    assert response.status == 200
    status = page.locator('[data-testid="automation-status-line"]')
    assert status.count() == 1
    assert status.inner_text().strip() == "Automatic linking is paused"
    assert (
        page.locator('[data-testid="automation-last-run"]').inner_text().strip()
        == "No run has completed yet."
    )
    assert page.locator('[data-testid="automation-activate-form"]').count() == 1
    assert page.locator('[data-testid="automation-pause-form"]').count() == 1
    assert page.recorded_errors == []


def test_the_preview_reads_the_recorded_scores_of_the_accepted_records(
    page, server: BrowserServer, login
) -> None:
    """The preview shows the recorded score of every accepted record in scope."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward/automation", wait_until="load")
    assert page.locator('[data-testid="automation-preview"]').count() == 0
    page.locator('[data-testid="automation-preview-button"]').click()
    page.wait_for_url("**/steward/automation?preview=1")
    table = page.locator('[data-testid="automation-preview"]')
    assert table.count() == 1
    rows = table.locator("tbody tr")
    assert rows.count() > 0
    count = page.locator('[data-testid="automation-preview-count"]').inner_text()
    assert "accepted records are shown" in count
    # Every row carries a score and a reading.  A score is never a decision.
    assert table.locator('[data-label="Score"]').first.inner_text().strip() != ""
    assert "would" in table.locator('[data-label="Reading"]').first.inner_text()
    assert page.recorded_errors == []


def test_activating_a_policy_records_the_reason_and_the_version(
    page, server: BrowserServer, login
) -> None:
    """The steward activates a policy with a reason, and the page shows it."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward/automation", wait_until="load")
    form = page.locator('[data-testid="automation-activate-form"]')
    form.locator('[data-testid="automation-mode"]').select_option("active")
    form.locator('[data-testid="automation-scope-applicant_profiles"]').check()
    form.locator('[data-testid="automation-activate-reason"]').fill(ACTIVATE_REASON)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and "/ui/actions/registry.automation.activate" in response.url
    ) as posted:
        form.locator('button[type="submit"]').click()
    response = posted.value
    assert response.status == 200
    assert response.json()["status"] == "accepted"
    page.wait_for_function(
        "() => document.querySelector('[data-testid=feedback-message]') !== null"
    )
    page.reload(wait_until="load")
    policy = page.locator('[data-testid="automation-policy"]').inner_text()
    assert "Version 1" in policy
    assert "Apply eligible links" in policy
    reason = page.locator('[data-testid="automation-policy-reason"]').inner_text()
    assert ACTIVATE_REASON in reason
    scope = page.locator('[data-testid="automation-scope"]').inner_text()
    assert "Applicant contact profiles" in scope
    assert page.recorded_errors == []


def test_pausing_the_automation_records_a_paused_policy(
    page, server: BrowserServer, login
) -> None:
    """The steward pauses the automation with a reason, and the page shows it."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward/automation", wait_until="load")
    form = page.locator('[data-testid="automation-pause-form"]')
    form.locator('[data-testid="automation-pause-reason"]').fill(PAUSE_REASON)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and "/ui/actions/registry.automation.pause" in response.url
    ) as posted:
        form.locator('button[type="submit"]').click()
    response = posted.value
    assert response.status == 200
    assert response.json()["status"] == "accepted"
    page.wait_for_function(
        "() => document.querySelector('[data-testid=feedback-message]') !== null"
    )
    page.reload(wait_until="load")
    policy = page.locator('[data-testid="automation-policy"]').inner_text()
    assert "Version 1" in policy
    assert "Paused" in policy
    status = page.locator('[data-testid="automation-status-line"]').inner_text()
    assert status.strip() == "Automatic linking is paused"
    assert page.recorded_errors == []


def test_the_reviewer_may_not_open_the_settings(
    page, server: BrowserServer, login
) -> None:
    """The policy controls are the steward's alone."""
    login("persona_permit_reviewer")
    response = page.goto(f"{server.base_url}/steward/automation", wait_until="load")
    assert response is not None
    assert response.status == 403


def test_the_settings_screen_fits_a_phone(
    viewport_390, server: BrowserServer, login
) -> None:
    """At 390 pixels the screen keeps every control inside the screen."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward/automation", wait_until="load")
    assert page.viewport_size == {"width": 390, "height": 844}
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert_not_covered(page, page.locator('[data-testid="automation-activate"]'))
    assert_not_covered(page, page.locator('[data-testid="automation-pause"]'))
    assert page.recorded_errors == []


@pytest.mark.parametrize("path", ("/steward/automation", "/steward/automation?preview=1"))
def test_no_screen_overflows_on_a_desktop(
    page, server: BrowserServer, login, path: str
) -> None:
    """The screen and its preview stay inside a desktop window."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}{path}", wait_until="load")
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 1, (path, overflow)
