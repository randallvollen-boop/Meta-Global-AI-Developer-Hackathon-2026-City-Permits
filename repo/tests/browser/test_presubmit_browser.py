"""The pre-submit check in a browser: every new button, including a disabled one."""

from __future__ import annotations

import json
import sqlite3

from conftest import BrowserServer

#: An address the city locator cannot place.  The applicant may type one.
MADE_UP = "12 Imaginary Lane"


def _fence(page, *, height: str, location: str, description: str, address: str = "400 Lantren Row") -> None:
    page.fill("#f-applicant_email", "demo.applicant@example.invalid")
    page.fill("#f-address_text", address)
    page.fill("#f-height_ft", height)
    page.fill("#f-fence_material", "cedar")
    page.select_option("#f-location", location)
    page.fill("#f-setback_ft", "2")
    page.check("#f-property_line_ack")
    page.fill("#f-project_description", description)
    page.set_input_files("#file-site_plan", {"name": "sketch.txt", "mimeType": "text/plain", "buffer": b"sketch"})
    page.set_input_files("#file-material_spec", {"name": "spec.txt", "mimeType": "text/plain", "buffer": b"cedar"})
    page.check("#f-certification_accepted")


def test_check_submit_and_submit_anyway(page, server: BrowserServer, login) -> None:
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    assert page.locator('[data-testid="must-fix"]').count() == 0
    _fence(page, height="4", location="side_rear", description="4 ft side fence")
    page.locator('[data-testid="check-application"]').click()
    page.wait_for_selector('[data-testid="looks-good"]')
    assert "None." in page.locator('[data-testid="must-fix"]').inner_text()
    assert page.locator('[data-testid="assistant-note"]').inner_text() == "The assistant is offline."
    submit = page.locator('[data-testid="submit-application"]')
    assert submit.is_enabled()
    submit.click()
    page.wait_for_url(lambda url: "/apply/submitted/" in url)

    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    _fence(page, height="6", location="front", description="6 ft front fence")
    page.locator('[data-testid="check-application"]').click()
    page.wait_for_selector('[data-testid="must-fix"]')
    must_fix = page.locator('[data-testid="must-fix"]')
    assert "ACME Code §14-305" in must_fix.inner_text()
    assert "Use 4 or less." in must_fix.inner_text()
    held = page.locator('[data-testid="submit-application"]')
    why = page.locator('[data-testid="submit-held-why"]')
    assert held.is_disabled()
    assert why.is_visible()
    assert why.inner_text() == "Fix the items under Must fix, or use Submit anyway."
    assert held.get_attribute("aria-describedby") == "submit-held-why"
    held.click(force=True)
    assert "/apply/submitted/" not in page.url

    anyway = page.locator('[data-testid="submit-anyway"]')
    anyway_why = page.locator('[data-testid="submit-anyway-why"]')
    assert anyway.is_disabled()
    assert anyway_why.is_visible()
    assert anyway_why.inner_text() == "Enter why submit now."
    assert anyway.get_attribute("aria-describedby") == "submit-anyway-why"
    anyway.click(force=True)
    assert "/apply/submitted/" not in page.url
    page.fill("#override-reason", "   ")
    assert anyway.is_disabled()
    assert anyway_why.is_visible()
    page.fill("#override-reason", "The fence is already built.")
    page.wait_for_function(
        "() => !document.querySelector(\"[data-testid='submit-anyway']\").disabled"
    )
    assert anyway_why.is_hidden()
    anyway.click()
    page.wait_for_url(lambda url: "/apply/submitted/" in url)
    reference = page.locator('[data-testid="submitted-reference"]').inner_text().strip()

    connection = sqlite3.connect(server.database)
    try:
        row = connection.execute(
            "select id from applications where source_application_number = ?",
            (reference,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/{row[0]}", wait_until="networkidle")
    assert page.locator('[data-testid="presubmit-flag"]').inner_text() == "Submitted with known issues"
    assert page.locator('[data-testid="presubmit-reason"]').inner_text() == (
        "The applicant said: The fence is already built."
    )
    assert page.recorded_errors == []


def test_an_address_the_city_cannot_match_still_submits(page, server: BrowserServer, login) -> None:
    """A made-up address is filed as typed: it never holds the application."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    _fence(
        page,
        height="4",
        location="side_rear",
        description="4 ft side fence",
        address=MADE_UP,
    )
    page.locator('[data-testid="check-application"]').click()
    page.wait_for_selector('[data-testid="should-check"]')
    assert "None." in page.locator('[data-testid="must-fix"]').inner_text()
    assert "We could not match this address to a parcel." in (
        page.locator('[data-testid="should-check"]').inner_text()
    )
    submit = page.locator('[data-testid="submit-application"]')
    assert submit.is_enabled()
    submit.click()
    page.wait_for_url(lambda url: "/apply/submitted/" in url)
    reference = page.locator('[data-testid="submitted-reference"]').inner_text().strip()
    assert reference

    connection = sqlite3.connect(server.database)
    try:
        row = connection.execute(
            "select submitted_facts from applications where source_application_number = ?",
            (reference,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    facts = json.loads(row[0]) if isinstance(row[0], str) else dict(row[0])
    assert facts["submitted_site_text"] == MADE_UP
    assert facts["parcel_number"] == ""
    assert page.recorded_errors == []


def test_a_must_fix_is_still_held_and_overridden_with_a_made_up_address(
    page, server: BrowserServer, login
) -> None:
    """A rule breach is held; the reason sends it, and the reviewer sees it."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    _fence(
        page,
        height="6",
        location="front",
        description="6 ft front fence",
        address=MADE_UP,
    )
    page.locator('[data-testid="check-application"]').click()
    page.wait_for_selector('[data-testid="must-fix"]')
    must_fix = page.locator('[data-testid="must-fix"]')
    assert "ACME Code §14-305" in must_fix.inner_text()
    assert "does not match a parcel" not in must_fix.inner_text()
    submit = page.locator('[data-testid="submit-application"]')
    assert submit.is_disabled()
    anyway = page.locator('[data-testid="submit-anyway"]')
    assert anyway.is_disabled()
    page.fill("#override-reason", "   ")
    assert anyway.is_disabled()
    page.fill("#override-reason", "The fence is already built.")
    page.wait_for_function(
        "() => !document.querySelector(\"[data-testid='submit-anyway']\").disabled"
    )
    anyway.click()
    page.wait_for_url(lambda url: "/apply/submitted/" in url)
    reference = page.locator('[data-testid="submitted-reference"]').inner_text().strip()

    connection = sqlite3.connect(server.database)
    try:
        row = connection.execute(
            "select id from applications where source_application_number = ?",
            (reference,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/{row[0]}", wait_until="networkidle")
    assert page.locator('[data-testid="presubmit-flag"]').inner_text() == "Submitted with known issues"
    assert page.locator('[data-testid="presubmit-reason"]').inner_text() == (
        "The applicant said: The fence is already built."
    )
    assert page.recorded_errors == []


def test_the_hold_is_lifted_when_the_applicant_fixes_the_rule(
    page, server: BrowserServer, login
) -> None:
    """The walkthrough's own step: check, fix the fence, then Submit application."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    _fence(
        page,
        height="6",
        location="front",
        description="6 ft front fence",
        address=MADE_UP,
    )
    page.locator('[data-testid="check-application"]').click()
    page.wait_for_selector('[data-testid="must-fix"]')
    submit = page.locator('[data-testid="submit-application"]')
    assert submit.is_disabled()
    page.fill("#f-height_ft", "4")
    page.wait_for_function(
        "() => !document.querySelector(\"[data-testid='submit-application']\").disabled"
    )
    assert "None." in page.locator('[data-testid="must-fix"]').inner_text()
    submit.click()
    page.wait_for_url(lambda url: "/apply/submitted/" in url)
    reference = page.locator('[data-testid="submitted-reference"]').inner_text().strip()
    assert reference
    assert page.recorded_errors == []


def test_the_hold_of_a_refused_submit_is_lifted_when_the_applicant_fixes_the_rule(
    page, server: BrowserServer, login
) -> None:
    """The server answers with the hold; the applicant answers it in place."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    _fence(
        page,
        height="6",
        location="front",
        description="6 ft front fence",
        address=MADE_UP,
    )
    # Submit application is pressed without a check: the server holds it.
    page.locator('[data-testid="submit-application"]').click()
    page.wait_for_selector('[data-testid="must-fix"]')
    submit = page.locator('[data-testid="submit-application"]')
    assert submit.is_disabled()
    assert page.locator('[data-testid="submit-anyway"]').count() == 1
    page.fill("#f-height_ft", "4")
    page.wait_for_function(
        "() => !document.querySelector(\"[data-testid='submit-application']\").disabled"
    )
    submit.click()
    page.wait_for_url(lambda url: "/apply/submitted/" in url)
    reference = page.locator('[data-testid="submitted-reference"]').inner_text().strip()
    assert reference
    # The server answers a held submit with 422, and the browser logs that as
    # a failed resource.  Nothing else went wrong.
    assert all("422" in error for error in page.recorded_errors), page.recorded_errors


def test_the_resident_path_of_the_walkthrough_runs_with_a_made_up_address(
    page, server: BrowserServer, login
) -> None:
    """Apply, let the agent route the case, and track it: the walkthrough's path."""
    # 1. Apply for a permit, with an address the City cannot place.
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    _fence(
        page,
        height="6",
        location="front",
        description="6 ft front fence",
        address=MADE_UP,
    )
    # 2. Check the application before it is sent, and answer the rule breach.
    page.locator('[data-testid="check-application"]').click()
    page.wait_for_selector('[data-testid="must-fix"]')
    page.fill("#f-height_ft", "4")
    page.wait_for_function(
        "() => !document.querySelector(\"[data-testid='submit-application']\").disabled"
    )
    page.locator('[data-testid="submit-application"]').click()
    page.wait_for_url(lambda url: "/apply/submitted/" in url)
    reference = page.locator('[data-testid="submitted-reference"]').inner_text().strip()
    assert reference

    # 3. The Agent Operator lets the agent route the case.
    login("persona_agent_operator")
    page.goto(f"{server.base_url}/agent/intake", wait_until="load")
    page.wait_for_selector('[data-testid="agent-toggle"]')
    if page.locator('[data-testid="agent-mode"]').inner_text().strip() == "asleep":
        page.locator('[data-testid="agent-toggle"]').click()
        page.wait_for_function(
            "() => document.querySelector('[data-testid=agent-mode]')"
            "?.textContent.trim() === 'awake'"
        )
    row = page.locator(f'[data-testid="agent-waiting-row"]:has-text("{reference}")')
    assert row.count() == 1, "the agent waits for the application of the resident"
    with page.expect_response(
        lambda response: "/ui/actions/agent.run.intake" in response.url
    ) as posted:
        row.locator('[data-testid="agent-run-one"]').click()
    assert posted.value.status == 200, posted.value.text()
    assert posted.value.json()["status"] == "accepted"

    # The case waits for a person: the City has to find the property.
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/early-resolution", wait_until="networkidle")
    case = page.locator(f'[data-testid="early-resolution-case"]:has-text("{reference}")')
    assert case.count() == 1, "the case is not on the early-resolution board"
    findings = case.locator('[data-testid="case-finding"]').all_text_contents()
    assert any("Address not found in the city locator" in text for text in findings), findings
    assert any("parcel" in text.lower() for text in findings), findings

    # 4. The applicant tracks the application.
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/track?ref={reference}", wait_until="networkidle")
    assert reference in page.content()
    assert page.recorded_errors == []
