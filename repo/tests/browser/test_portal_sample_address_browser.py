"""The sample addresses of the applicant form in a real browser.

The button beside the address field lists addresses of the City that match a
parcel.  Picking one fills the field, the locator checks it, and the case
that arrives carries the parcel of that address.
"""

from __future__ import annotations

import json
import sqlite3

from conftest import BrowserServer


def test_a_sample_address_fills_the_field_and_the_case_lands_with_its_parcel(
    page, server: BrowserServer, login
) -> None:
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")

    button = page.locator('[data-testid="sample-address-button"]')
    assert button.is_visible()
    assert button.inner_text() == "Use a sample address"
    assert page.locator('[data-testid="sample-address-note"]').inner_text() == (
        "Fictional addresses that match the City's map."
    )

    options = page.locator('[data-testid="sample-address-option"]')
    count = options.count()
    assert 5 <= count <= 8, count
    # The list is closed until the button is pressed.
    assert not options.first.is_visible()
    button.click()
    assert options.first.is_visible()

    address = options.first.get_attribute("data-address")
    parcel = options.first.get_attribute("data-parcel")
    assert address and parcel
    options.first.click()
    assert page.locator("#f-address_text").input_value() == address
    # The locator checked the address and named the parcel of it.
    page.wait_for_function(
        "() => { const note = document.querySelector('[data-testid=\"did-you-mean\"]');"
        " return note !== null && note.textContent.indexOf('Parcel') !== -1; }"
    )
    assert parcel in page.locator('[data-testid="did-you-mean"]').inner_text()

    # The rest of the application is filed with that address.
    page.fill("#f-applicant_email", "demo.applicant@example.invalid")
    page.fill("#f-height_ft", "4")
    page.fill("#f-fence_material", "cedar")
    page.select_option("#f-location", "side_rear")
    page.fill("#f-setback_ft", "2")
    page.check("#f-property_line_ack")
    page.fill("#f-project_description", "4 ft side fence at a sample address")
    page.set_input_files(
        "#file-site_plan", {"name": "sketch.txt", "mimeType": "text/plain", "buffer": b"sketch"}
    )
    page.set_input_files(
        "#file-material_spec", {"name": "spec.txt", "mimeType": "text/plain", "buffer": b"cedar"}
    )
    page.check("#f-certification_accepted")
    page.locator('[data-testid="submit-application"]').click()
    page.wait_for_url(lambda url: "/apply/submitted/" in url)
    reference = page.locator('[data-testid="submitted-reference"]').inner_text().strip()

    connection = sqlite3.connect(server.database)
    try:
        row = connection.execute(
            "select id, submitted_facts from applications where source_application_number = ?",
            (reference,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    facts = json.loads(row[1])
    assert facts["parcel_number"] == parcel
    assert facts["submitted_parcel"] == parcel
    assert facts["submitted_site_text"] == address
    assert page.recorded_errors == []
