"""The pre-submit check in a browser: every new button, including a disabled one."""

from __future__ import annotations

import sqlite3

from conftest import BrowserServer


def _fence(page, *, height: str, location: str, description: str) -> None:
    page.fill("#f-applicant_email", "demo.applicant@example.invalid")
    page.fill("#f-address_text", "400 Lantren Row")
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
