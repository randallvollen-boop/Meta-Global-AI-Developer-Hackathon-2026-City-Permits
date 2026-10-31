"""The City frame in a browser: the permit path, the help link and the disclosure.

The City website is the front door of the demonstration.  Every control the
visitor can use is clicked here: the call to action that opens the
application, the footer link to the contact page and the disclosure that
holds the other City services.
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

from conftest import BrowserServer


def test_the_apply_call_to_action_opens_the_application(
    page, server: BrowserServer, login
) -> None:
    """The home page call to action leads into the application."""
    login("persona_applicant")
    assert page.url.split("?")[0].rstrip("/") == f"{server.base_url}/city"

    page.locator('[data-testid="hero-permits"]').click()
    page.wait_for_url(f"{server.base_url}/city/permits")

    page.locator('[data-testid="permits-start"]').click()
    page.wait_for_url(f"{server.base_url}/apply")
    assert page.locator('[data-testid="type-card"]').count() > 0
    assert page.recorded_errors == []


def test_the_footer_help_link_opens_the_contact_page(
    page, server: BrowserServer, login
) -> None:
    """The footer Help link answers with the contact page."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/city/", wait_until="domcontentloaded")

    page.locator('[data-testid="city-footer-help"]').click()
    page.wait_for_url(f"{server.base_url}/city/contact")
    assert page.locator("h1").first.inner_text().strip() == "Contact the City"
    assert page.recorded_errors == []


def test_the_other_city_services_sit_behind_a_disclosure(
    page, server: BrowserServer, login
) -> None:
    """The other services are collapsed until the visitor asks for them."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/city/", wait_until="domcontentloaded")

    disclosure = page.locator('[data-testid="more-services"]')
    assert disclosure.count() == 1
    assert disclosure.evaluate("node => node.open") is False
    # The permit tiles stay visible.
    assert page.locator('[data-testid="tile-permits"]').is_visible()
    assert page.locator('[data-testid="tile-community"]').is_visible()
    # The other services do not.
    assert not page.locator('[data-testid="tile-trash-recycling"]').is_visible()

    page.locator('[data-testid="more-services"] > summary').click()
    assert page.locator('[data-testid="tile-trash-recycling"]').is_visible()
    assert page.locator('[data-testid="tile-parks"]').is_visible()
    page.locator('[data-testid="tile-parks"]').click()
    page.wait_for_url(f"{server.base_url}/city/parks")
    assert page.locator("h1").first.inner_text().strip() == "Parks and recreation"
    assert page.recorded_errors == []
