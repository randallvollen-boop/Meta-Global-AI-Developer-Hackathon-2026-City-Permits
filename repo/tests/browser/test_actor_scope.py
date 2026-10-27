"""The browser check of the actor scope.

A persona only reaches the records and the actions its grants cover: an
applicant never opens another applicant, a data steward never decides or
issues a permit, a configuration grant never approves a business action, a
reviewer never edits a receipt, and an applicant never inspects a steward
candidate.
"""
# REQUIRES: SEC-01, SEC-02, SEC-03, UX-01, EDIT-02
# The scope of a persona reaches the screens, the direct links, the records
# and the actions of the interface.

from __future__ import annotations

from conftest import BrowserServer


def test_the_applicant_cannot_open_another_applicant(
    page, server: BrowserServer, login
) -> None:
    login("persona_applicant")
    response = page.goto(f"{server.base_url}/applicants/party_cedarline")
    assert response is not None
    assert response.status == 404
    assert page.locator('[data-testid="error-panel"]').count() == 1
    assert "Cedarline" not in page.content()


def test_the_applicant_only_sees_its_own_case(page, server: BrowserServer, login) -> None:
    login("persona_applicant")
    page.goto(f"{server.base_url}/permits/app_synth_001")
    assert "not available to you" in page.content()
    response = page.goto(f"{server.base_url}/permits/app_d05")
    assert response is not None
    assert response.status == 200


def test_the_applicant_may_not_inspect_the_steward_candidates(
    page, server: BrowserServer, login
) -> None:
    login("persona_applicant")
    response = page.goto(f"{server.base_url}/steward")
    assert response is not None
    assert response.status == 403
    body = page.content()
    assert "PER-AP-0003" not in body
    assert "party_cedarline" not in body


def test_the_data_steward_cannot_decide_or_issue_a_permit(
    page, server: BrowserServer, login
) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    for action_id in ("permit.decide", "permit.issue"):
        details = page.locator(f'details[data-action-id="{action_id}"]')
        assert details.count() == 1
        assert details.get_attribute("data-permitted") == "false"
        details.locator("summary").click()
        reason = details.locator('[data-testid="action-denied-reason"]')
        assert reason.is_visible()
        assert "permit." in reason.inner_text()


def test_the_configuration_grant_alone_cannot_approve_a_business_action(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    for action_id in ("permit.decide", "permit.issue"):
        details = page.locator(f'details[data-action-id="{action_id}"]')
        assert details.get_attribute("data-permitted") == "false"


def test_the_reviewer_cannot_edit_a_receipt(page, server: BrowserServer, login) -> None:
    login("persona_permit_reviewer")
    response = page.goto(f"{server.base_url}/reconciliation")
    assert response is not None
    assert response.status == 403
    body = page.content()
    assert "Confirm allocation" not in body
    assert "Import ERP payment" not in body


def test_the_reviewer_may_not_open_the_governance_screen(
    page, server: BrowserServer, login
) -> None:
    login("persona_permit_reviewer")
    response = page.goto(f"{server.base_url}/governance")
    assert response is not None
    assert response.status == 403


def test_the_applicant_cannot_write_a_review_decision(
    page, server: BrowserServer, login
) -> None:
    login("persona_applicant")
    page.goto(f"{server.base_url}/permits/app_d05", wait_until="domcontentloaded")
    details = page.locator('details[data-action-id="permit.decide"]')
    assert details.get_attribute("data-permitted") == "false"
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    assert token
    response = page.request.post(
        f"{server.base_url}/ui/actions/permit.decide",
        form={
            "application_id": "app_d05",
            "outcome": "approved",
            "reason": "the browser asked for it",
            "csrf_token": token,
            "next": "/permits/app_d05",
        },
    )
    assert response.status == 403
    assert "permit.decide" in response.text()
