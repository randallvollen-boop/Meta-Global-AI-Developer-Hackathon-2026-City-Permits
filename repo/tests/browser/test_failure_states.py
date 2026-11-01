"""The browser walkthrough of the failure states.

A source that does not answer, a source that refuses, a stale expected
version and a write without the CSRF token all leave the accepted state
untouched, and the interface reports the refusal instead of a success.
"""
# REQUIRES: CHG-02, CHG-06, EDIT-04, UX-04, SEC-02
# The interface reports the acknowledgement of the source, refuses a stale
# write, refuses a write without the token of the session, and never shows a
# success for work the source has not acknowledged.

from __future__ import annotations

from conftest import BrowserServer


def test_a_source_that_does_not_answer_leaves_the_accepted_value(
    page, server: BrowserServer, login, submit_action
) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/applicants/party_applicant_1", wait_until="domcontentloaded")
    before = page.request.get(
        f"{server.base_url}/api/sources/permitting/applicant_profiles/snapshots",
        params={"record_id": "PER-AP-0001"},
    ).json()["snapshots"]
    message = submit_action(
        "source.write",
        {"payload": '{"_demo_control": {"mode": "timeout"}}'},
    )
    assert "did not answer in time" in message
    # The detail list of the last action sits behind the disclosure of the
    # frame (demo polish, P3), so it is opened before it is read.
    page.locator('[data-testid="feedback-more"] > summary').click()
    assert page.locator('[data-testid="feedback-pending"]').inner_text().startswith("yes")
    after = page.request.get(
        f"{server.base_url}/api/sources/permitting/applicant_profiles/snapshots",
        params={"record_id": "PER-AP-0001"},
    ).json()["snapshots"]
    assert len(after) == len(before)
    assert after[0]["source_record_version"] == before[0]["source_record_version"]


def test_a_source_that_refuses_reports_the_refusal(
    page, server: BrowserServer, login, submit_action
) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/applicants/party_applicant_1", wait_until="domcontentloaded")
    message = submit_action(
        "source.write",
        {"payload": '{"_demo_control": {"mode": "reject"}}'},
    )
    assert "refused the change" in message
    assert "kept its accepted value" in message


def test_a_stale_expected_version_is_refused(
    page, server: BrowserServer, login, submit_action
) -> None:
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    # The validation runs outside this screen, so the form on the screen still
    # carries the version the screen was rendered with, and the validation has
    # moved the record on since then.  (The screen reads itself again after an
    # action it sends itself, so the move has to come from elsewhere.)
    evaluated = page.request.post(
        f"{server.base_url}/api/permits/applications/app_synth_001/evaluate"
    )
    assert evaluated.ok, evaluated.text()
    message = submit_action(
        "permit.decide",
        {
            "application_id": "app_synth_001",
            "outcome": "approved",
            "reason": "a decision against a version that has moved on",
        },
    )
    assert "changed since it was read" in message
    assert page.locator('[data-testid="feedback"]').get_attribute("data-outcome") == "denied"
    evaluations = page.request.get(
        f"{server.base_url}/api/permits/applications/app_synth_001/evaluations"
    ).json()["evaluations"]
    assert len(evaluations) == 1
    decisions = page.request.get(
        f"{server.base_url}/api/permits/applications/app_synth_001"
    ).json()
    assert decisions["status"] != "approved"


def test_a_write_without_the_token_of_the_session_is_refused(
    page, server: BrowserServer, login
) -> None:
    login("persona_permit_reviewer")
    response = page.request.post(
        f"{server.base_url}/ui/actions/permit.evaluate",
        form={"application_id": "app_synth_001", "next": "/permits/app_synth_001"},
    )
    assert response.status == 403
    evaluations = page.request.get(
        f"{server.base_url}/api/permits/applications/app_synth_001/evaluations"
    ).json()["evaluations"]
    assert evaluations == []


def test_the_browser_refuses_an_incomplete_form_before_it_reaches_the_server(
    page, server: BrowserServer, login
) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/rules-fees", wait_until="domcontentloaded")
    before = page.request.get(f"{server.base_url}/api/rules").json()["versions"]
    sent: list[str] = []
    page.on(
        "request",
        lambda request: sent.append(request.url)
        if "/ui/actions/rule.draft" in request.url
        else None,
    )
    # Changed deliberately (demo polish, AD3): draft a new version is closed.
    page.locator('details.panel:has([data-action-id="rule.draft"]) > summary').click()
    details = page.locator('details[data-action-id="rule.draft"]').first
    details.locator("summary").click()
    form = details.locator("form.action-form")
    form.locator('[name="rule_id"]').fill("CT-9")
    form.locator('[name="title"]').fill("a demonstration rule without a citation")
    form.locator('[name="effective_from"]').fill("2026-01-01T00:00:00Z")
    form.locator('[name="reason"]').fill("the citation is missing")
    form.locator('button[type="submit"]').click()
    page.wait_for_timeout(500)
    assert sent == []
    assert form.locator('[name="citation"]').evaluate("element => !element.checkValidity()")
    after = page.request.get(f"{server.base_url}/api/rules").json()["versions"]
    assert len(after) == len(before)


def test_the_server_refuses_a_rule_draft_without_a_citation(
    page, server: BrowserServer, login
) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/rules-fees", wait_until="domcontentloaded")
    before = page.request.get(f"{server.base_url}/api/rules").json()["versions"]
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    response = page.request.post(
        f"{server.base_url}/ui/actions/rule.draft",
        form={
            "rule_id": "CT-9",
            "permit_type_key": "com_ti",
            "title": "a demonstration rule without a citation",
            "effective_from": "2026-01-01T00:00:00Z",
            "reason": "the citation is missing",
            "csrf_token": token,
            "next": "/rules-fees",
        },
    )
    assert response.status >= 400
    after = page.request.get(f"{server.base_url}/api/rules").json()["versions"]
    assert len(after) == len(before)
