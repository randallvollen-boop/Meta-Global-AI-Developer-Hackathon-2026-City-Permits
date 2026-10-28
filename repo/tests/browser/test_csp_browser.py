"""The Content Security Policy breaks nothing the interface does.

Every page below runs with the real policy from ``core/security.py``.  A blocked
script, style or request is reported by the browser as a console error, which
the ``page`` fixture records.
"""
# REQUIRES: UX-01, SEC-02

from __future__ import annotations

from conftest import BrowserServer


def test_pages_load_under_the_policy_without_violations(page, server: BrowserServer, login) -> None:
    login("persona_data_steward")
    for path in ("/queue", "/steward", "/masters"):
        response = page.goto(f"{server.base_url}{path}", wait_until="networkidle")
        assert response is not None
        policy = response.headers["content-security-policy"]
        assert "script-src 'self'" in policy
        assert response.headers["x-content-type-options"] == "nosniff"
    assert page.recorded_errors == []


def test_theme_drawer_and_demo_switch_work_under_the_policy(page, server: BrowserServer, login) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue", wait_until="networkidle")
    before = page.evaluate("document.documentElement.getAttribute('data-theme')")
    page.locator("#theme-toggle").click()
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") != before
    # Open the demo controls and switch persona: a form post to the same origin.
    page.locator('[data-testid="demo-switch"] summary').click()
    page.locator('button[data-demo-persona="persona_permit_reviewer"]').click()
    page.wait_for_url(f"{server.base_url}/queue")
    assert "Permit Reviewer" in page.locator('[data-testid="acting-persona"]').inner_text()
    assert page.recorded_errors == []


def test_city_website_and_help_panel_load_under_the_policy(page, server: BrowserServer, login) -> None:
    login("persona_applicant")
    response = page.goto(f"{server.base_url}/city/", wait_until="networkidle")
    assert response is not None
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    page.goto(f"{server.base_url}/apply", wait_until="networkidle")
    assert page.recorded_errors == []
