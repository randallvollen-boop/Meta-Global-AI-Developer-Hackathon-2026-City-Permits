"""The pre-submit check in a browser: every new button, including a disabled one."""

from __future__ import annotations

import json
import sqlite3

import pytest

from conftest import BrowserServer, assert_no_horizontal_overflow

#: An address the city locator cannot place.  The applicant may type one.
MADE_UP = "12 Imaginary Lane"

#: An address the city locator knows, with the parcel it falls in.
KNOWN = "400 Lantern Row"

#: The parcel the locator places the known address in.
KNOWN_PARCEL = "ACME-P-1001"


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


def _pick_suggestion(page, prefix: str) -> str:
    """Return the address a person picks from the suggestions of the City."""
    field = page.locator("#f-address_text")
    field.fill(prefix)
    page.wait_for_function(
        "(prefix) => Array.from(document.querySelectorAll('#address-suggest option'))"
        ".some((option) => option.value.indexOf(prefix + ',') === 0)",
        arg=prefix,
    )
    offered = page.locator("#address-suggest option").evaluate_all(
        "options => options.map((option) => option.value)"
    )
    # The plain street address, not one of the units on the same street.
    chosen = next(value for value in offered if value.startswith(prefix + ","))
    field.fill(chosen)
    return chosen


def _boxes(page, selector: str) -> list[dict[str, float]]:
    """Return the box of every element the selector names."""
    return page.locator(selector).evaluate_all(
        "nodes => nodes.map((node) => {"
        " const box = node.getBoundingClientRect();"
        " return {x: box.x, y: box.y, top: box.top, bottom: box.bottom,"
        "  width: box.width, height: box.height};"
        "})"
    )


def test_check_submit_and_submit_anyway(page, server: BrowserServer, login) -> None:
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    assert page.locator('[data-testid="must-fix"]').count() == 0
    _fence(page, height="4", location="side_rear", description="4 ft side fence")
    page.locator('[data-testid="check-application"]').click()
    page.wait_for_selector('[data-testid="looks-good"]')
    assert "None." in page.locator('[data-testid="must-fix"]').inner_text()
    note = page.locator('[data-testid="assistant-note"]')
    assert "The assistant is offline." in note.inner_text()
    assert note.locator('[data-testid="presubmit-muse-badge"]').inner_text() == "Muse"
    assert note.locator('[data-testid="presubmit-muse-lead"]').inner_text() == "Muse says:"
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
    assert anyway_why.inner_text() == "Write why you are submitting now."
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


def test_a_broken_rule_at_a_real_property_still_lets_the_applicant_submit(
    page, server: BrowserServer, login
) -> None:
    """The address the City knows: the rule holds it, the reason still sends it.

    The property is one the locator places, so nothing about the address is
    waiting for a person.  The rule is still broken, so the application is
    held until the applicant says why, and the reason sends it.
    """
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    address = _pick_suggestion(page, KNOWN)
    # The City placed the address: it is a real parcel.
    page.wait_for_function(
        "(parcel) => document.querySelector('[data-testid=did-you-mean]')"
        ".textContent.indexOf(parcel) !== -1",
        arg=KNOWN_PARCEL,
    )
    _fence(page, height="6", location="front", description="6 ft front fence", address=address)
    page.locator('[data-testid="check-application"]').click()
    page.wait_for_selector('[data-testid="must-fix"]')
    must_fix = page.locator('[data-testid="must-fix"]')
    assert "ACME Code §14-305" in must_fix.inner_text()
    assert "Use 4 or less." in must_fix.inner_text()
    # The address matched, so it is not a review issue of its own.
    assert "We could not match this address to a parcel." not in (
        page.locator('[data-testid="should-check"]').inner_text()
    )
    submit = page.locator('[data-testid="submit-application"]')
    assert submit.is_disabled()
    assert page.locator('[data-testid="submit-held-why"]').is_visible()
    anyway = page.locator('[data-testid="submit-anyway"]')
    assert anyway.is_disabled()
    page.fill("#override-reason", "The fence is already built.")
    page.wait_for_function(
        "() => !document.querySelector(\"[data-testid='submit-anyway']\").disabled"
    )
    anyway.click()
    page.wait_for_url(lambda url: "/apply/submitted/" in url)
    reference = page.locator('[data-testid="submitted-reference"]').inner_text().strip()
    assert reference

    connection = sqlite3.connect(server.database)
    try:
        row = connection.execute(
            "select id, submitted_facts from applications where source_application_number = ?",
            (reference,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    facts = json.loads(row[1]) if isinstance(row[1], str) else dict(row[1])
    assert facts["parcel_number"] == KNOWN_PARCEL
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/{row[0]}", wait_until="networkidle")
    assert page.locator('[data-testid="presubmit-flag"]').inner_text() == "Submitted with known issues"
    assert page.locator('[data-testid="presubmit-reason"]').inner_text() == (
        "The applicant said: The fence is already built."
    )
    assert page.recorded_errors == []


def test_the_override_works_after_a_refused_submit_at_a_real_property(
    page, server: BrowserServer, login
) -> None:
    """The City answers the pressed Submit: the hold, the reason, the receipt.

    This is the path the applicant walks without the review of the browser:
    Submit application is pressed, the City holds it and renders the reason
    field itself, and the reason still sends the application.
    """
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    address = _pick_suggestion(page, KNOWN)
    _fence(page, height="6", location="front", description="6 ft front fence", address=address)
    page.locator('[data-testid="submit-application"]').click()
    page.wait_for_selector('[data-testid="must-fix"]')
    assert "ACME Code §14-305" in page.locator('[data-testid="must-fix"]').inner_text()
    submit = page.locator('[data-testid="submit-application"]')
    assert submit.is_disabled()
    anyway = page.locator('[data-testid="submit-anyway"]')
    assert anyway.is_disabled()
    assert page.locator('[data-testid="submit-anyway-why"]').is_visible()
    page.fill("#override-reason", "The fence is already built.")
    page.wait_for_function(
        "() => !document.querySelector(\"[data-testid='submit-anyway']\").disabled"
    )
    anyway.click()
    page.wait_for_url(lambda url: "/apply/submitted/" in url)
    reference = page.locator('[data-testid="submitted-reference"]').inner_text().strip()
    assert reference

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
    # The City answers a held submit with 422, and the browser logs that as a
    # failed resource.  Nothing else went wrong.
    assert all("422" in error for error in page.recorded_errors), page.recorded_errors


def test_the_buttons_of_a_held_form_share_one_row_and_stack_on_a_phone(
    page, server: BrowserServer, login
) -> None:
    """The action row of a held form: one row on a desk, clean lines on a phone."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    _fence(page, height="6", location="front", description="6 ft front fence")
    page.locator('[data-testid="check-application"]').click()
    page.wait_for_selector('[data-testid="must-fix"]')

    boxes = _boxes(page, ".form-buttons .btn")
    assert len(boxes) == 5, boxes
    assert len({round(box["top"]) for box in boxes}) == 1, boxes
    assert len({round(box["height"]) for box in boxes}) == 1, boxes
    # The disabled button says why it is off, beside it, in words.
    button = _boxes(page, "[data-testid='submit-anyway']")[0]
    why = _boxes(page, "[data-testid='submit-anyway-why']")[0]
    assert page.locator('[data-testid="submit-anyway"]').is_disabled()
    assert page.locator('[data-testid="submit-anyway-why"]').is_visible()
    assert why["x"] >= button["x"] + button["width"], (button, why)
    assert why["top"] < button["bottom"] and why["bottom"] > button["top"], (button, why)
    # The reason is a field of the form like any other: the label is above
    # it, and the box carries the field style of the other fields.
    label = _boxes(page, "label[for='override-reason']")[0]
    area = _boxes(page, "[data-testid='why-submit-now']")[0]
    assert label["bottom"] <= area["top"] + 1, (label, area)
    field_style = page.evaluate(
        "() => {"
        " const read = (node) => { const style = getComputedStyle(node);"
        "  return [style.fontFamily, style.fontSize, style.borderTopWidth, style.borderTopStyle,"
        "   style.borderTopColor, style.backgroundColor, style.borderRadius, style.padding]; };"
        " return {own: read(document.querySelector('[data-testid=why-submit-now]')),"
        "  other: read(document.querySelector('#f-project_description'))};"
        "}"
    )
    assert field_style["own"] == field_style["other"], field_style
    page.fill("#override-reason", "The fence is already built.")
    page.wait_for_function(
        "() => !document.querySelector(\"[data-testid='submit-anyway']\").disabled"
    )
    # The button is the quiet one of the application: the same button as the
    # other quiet one on the page.
    classes = (page.locator("[data-testid='submit-anyway']").get_attribute("class") or "").split()
    assert "btn" in classes and "ghost" in classes, classes
    quiet = page.evaluate(
        "() => {"
        " const read = (node) => { const style = getComputedStyle(node);"
        "  return [style.backgroundColor, style.color, style.borderRadius]; };"
        " return {own: read(document.querySelector('[data-testid=submit-anyway]')),"
        "  other: read(document.querySelector('a.btn.ghost'))};"
        "}"
    )
    assert quiet["own"] == quiet["other"], quiet

    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(200)
    boxes = _boxes(page, ".form-buttons .btn")
    assert len({round(box["top"]) for box in boxes}) > 1, boxes
    for box in boxes:
        assert box["x"] >= 0, boxes
        assert box["x"] + box["width"] <= 390, boxes
    assert_no_horizontal_overflow(page)
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


#: The address Randall typed.  The city locator does not place it.
UNMATCHED_STREET = "123 main street"


@pytest.fixture(params=["chromium", "webkit"])
def held_browser(request):
    """A Chromium or WebKit browser for the held-submit walk."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    engine = request.param
    with sync_playwright() as playwright:
        launcher = getattr(playwright, engine)
        try:
            if engine == "chromium":
                browser = launcher.launch(args=["--no-sandbox"])
            else:
                browser = launcher.launch()
        except PlaywrightError as exc:
            if engine == "webkit":
                pytest.skip(f"WebKit is not available: {exc}")
            raise
        try:
            yield browser
        finally:
            browser.close()


def _person(browser, server: BrowserServer, *, java_script: bool):
    """Return a signed-in applicant page, with or without JavaScript."""
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        java_script_enabled=java_script,
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    page.on(
        "console",
        lambda message: errors.append(f"console: {message.text}")
        if message.type == "error"
        else None,
    )
    page.recorded_errors = errors  # type: ignore[attr-defined]
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator('button[data-persona="persona_applicant"]').click()
    page.wait_for_url(f"{server.base_url}/city/")
    return context, page


def _held_unmatched(page, server: BrowserServer) -> None:
    """Fill the unmatched 6 ft front fence, submit, and land on the held page."""
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="domcontentloaded")
    _fence(
        page,
        height="6",
        location="front",
        description="6 ft front fence",
        address=UNMATCHED_STREET,
    )
    page.locator('[data-testid="submit-application"]').click()
    page.wait_for_selector('[data-testid="must-fix"]')
    page.wait_for_selector('[data-testid="why-submit-now"]')


def _assert_reload_kept_the_documents(page) -> None:
    """The reload's file inputs are empty; the draft still has the documents."""
    assert page.locator("#file-site_plan").evaluate("el => el.files.length") == 0
    assert page.locator("#file-material_spec").evaluate("el => el.files.length") == 0
    assert page.locator('[data-doc-type="site_plan"]').get_attribute("data-added") == "true"
    assert page.locator('[data-doc-type="material_spec"]').get_attribute("data-added") == "true"


def test_submit_anyway_after_a_held_reload(held_browser, server: BrowserServer) -> None:
    """Submit, then on the held page type a reason only, and receive a reference.

    Nothing else is edited.  The documents are only on the draft, and a live
    check must still call the application complete and held.
    """
    context, page = _person(held_browser, server, java_script=True)
    try:
        _held_unmatched(page, server)
        assert "ACME Code §14-305" in page.locator('[data-testid="must-fix"]').inner_text()
        assert "We could not match this address to a parcel." in (
            page.locator('[data-testid="should-check"]').inner_text()
        )
        assert page.locator('[data-testid="why-submit-now"]').is_visible()
        assert page.locator('[data-testid="submit-anyway"]').is_visible()
        assert page.locator('[data-testid="submit-application"]').is_disabled()
        _assert_reload_kept_the_documents(page)
        page.wait_for_function(
            "() => document.querySelector(\"[data-testid='submit-anyway']\").disabled"
        )
        with page.expect_response(
            lambda response: response.url.endswith("/check") and response.request.method == "POST"
        ) as checked:
            page.locator("#f-project_description").evaluate(
                "el => el.dispatchEvent(new Event('input', {bubbles: true}))"
            )
        body = checked.value.json()
        assert body["can_submit"] is True, body
        assert body["missing"] == [] and body["blocking"] == []
        assert body["review"]["held"] is True, body
        assert page.locator('[data-testid="why-submit-now"]').is_visible()
        assert page.locator('[data-testid="submit-anyway"]').is_visible()
        assert page.locator('[data-testid="submit-application"]').is_disabled()
        page.fill("#override-reason", "The fence is already built.")
        page.wait_for_function(
            "() => !document.querySelector(\"[data-testid='submit-anyway']\").disabled"
        )
        page.locator('[data-testid="submit-anyway"]').click()
        page.wait_for_url(lambda url: "/apply/submitted/" in url)
        reference = page.locator('[data-testid="submitted-reference"]').inner_text().strip()
        assert reference
        assert all("422" in error for error in page.recorded_errors), page.recorded_errors
    finally:
        context.close()


def test_the_real_held_submit_path_keeps_the_override_after_tour_typing_and_enter(
    page, server: BrowserServer, login
) -> None:
    """At 1280px, the tour, address picker, stored uploads and Enter keep a hold.

    This is the applicant's reported sequence.  Documents are first stored by
    the document widgets, so the refused Submit posts no file bytes.  Typing
    then calls /check, and the first (hidden) submitter is exercised with an
    Enter key before the person uses Submit anyway.
    """
    login("persona_applicant")
    page.set_viewport_size({"width": 1280, "height": 900})

    # Reach the application form from the resident tour, rather than a direct
    # address bar navigation.  The overlay itself never fills story answers.
    page.evaluate("() => window.acmeTour.start('resident')")
    for title in (
        "A fence for the back yard",
        "Ask which permit a fence needs",
        "Apply for a permit",
    ):
        page.wait_for_function(
            "(title) => document.querySelector('[data-testid=tour-title]')?.textContent.trim() === title",
            arg=title,
        )
        page.locator('[data-testid="tour-next"]').click()
    page.wait_for_url(f"{server.base_url}/apply/deck_fence")
    page.locator('[data-testid="tour-exit"]').click()

    # Type into the suggest box and select the offered, known address.
    address = _pick_suggestion(page, KNOWN)
    _fence(page, height="6", location="front", description="6 ft front fence", address=address)

    # The upload widgets store both files on the draft before Submit.  Opening
    # the draft again proves that its input controls are empty while Added is
    # still visible, which is the real post-reload condition.
    page.locator('[data-testid="save-draft"]').click()
    page.wait_for_url(lambda url: "/apply/track?tab=drafts&saved=" in url)
    draft = page.url.rsplit("saved=", 1)[1]
    page.goto(f"{server.base_url}/apply/deck_fence?draft={draft}", wait_until="networkidle")
    _assert_reload_kept_the_documents(page)

    # Submit has no selected files now.  The server holds it, and typing on
    # that held page causes the live completeness/rules check to finish.
    page.locator('[data-testid="submit-application"]').click()
    page.wait_for_selector('[data-testid="must-fix"]')
    with page.expect_response(
        lambda response: response.url.endswith("/check") and response.request.method == "POST"
    ) as checked:
        page.locator("#f-project_description").fill("6 ft front fence, checked again")
    body = checked.value.json()
    assert body["can_submit"] is True, body
    assert body["review"]["held"] is True, body
    assert page.locator('[data-testid="why-submit-now"]').is_visible()
    anyway = page.locator('[data-testid="submit-anyway"]')
    assert anyway.is_visible() and anyway.is_disabled()

    # Browser implicit submission uses the hidden intent=update button.  It
    # must re-render the held review, rather than saving a draft without it.
    with page.expect_response(
        lambda response: response.url.endswith("/apply/deck_fence")
        and response.request.method == "POST"
    ) as updated:
        page.locator("#f-applicant_email").press("Enter")
    assert updated.value.status == 422
    page.wait_for_selector('[data-testid="why-submit-now"]')
    assert page.locator('[data-testid="why-submit-now"]').is_visible()
    assert page.locator('[data-testid="submit-anyway"]').is_visible()

    page.fill("#override-reason", "The fence is already built.")
    page.wait_for_function(
        "() => !document.querySelector(\"[data-testid='submit-anyway']\").disabled"
    )
    anyway.click()
    page.wait_for_url(lambda url: "/apply/submitted/" in url)
    assert page.locator('[data-testid="submitted-reference"]').inner_text().strip()
    assert all("422" in error for error in page.recorded_errors), page.recorded_errors


def test_submit_anyway_posts_without_javascript(held_browser, server: BrowserServer) -> None:
    """The same walk with no script: the reason is a plain form post."""
    context, page = _person(held_browser, server, java_script=False)
    try:
        _held_unmatched(page, server)
        assert "ACME Code §14-305" in page.locator('[data-testid="must-fix"]').inner_text()
        assert page.locator('[data-testid="why-submit-now"]').is_visible()
        anyway = page.locator('[data-testid="submit-anyway"]')
        assert anyway.is_visible()
        assert anyway.is_enabled()
        assert page.locator('[data-testid="submit-application"]').is_disabled()
        _assert_reload_kept_the_documents(page)
        page.fill("#override-reason", "The fence is already built.")
        assert anyway.is_enabled()
        anyway.click()
        page.wait_for_url(lambda url: "/apply/submitted/" in url)
        reference = page.locator('[data-testid="submitted-reference"]').inner_text().strip()
        assert reference
        assert all("422" in error for error in page.recorded_errors), page.recorded_errors
    finally:
        context.close()
