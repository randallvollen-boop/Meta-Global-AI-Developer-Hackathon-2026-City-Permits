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


def test_agent_status_refresh_loads_under_the_policy(page, server: BrowserServer, login) -> None:
    """The optional same-origin refresh script is allowed by the real policy."""
    login("persona_agent_operator")
    response = page.goto(f"{server.base_url}/agents", wait_until="networkidle")
    assert response is not None
    assert "script-src 'self'" in response.headers["content-security-policy"]
    # The page marks itself as one that must not be left.
    page.evaluate("() => { window.__noNav = 1; }")
    value = page.locator("[data-testid='agent-operator-summary'] .kpi .v").first
    original = value.inner_text().strip()
    value.evaluate("(node) => { node.textContent = '999'; }")
    with page.expect_response(
        lambda answer: answer.request.method == "GET"
        and answer.url.endswith("/agents")
        and answer.request.resource_type == "fetch"
    ) as refreshed:
        page.locator("[data-testid='agent-status-refresh']").click()
    assert refreshed.value.status == 200
    # The page was not replaced: the marker of the page is still there.
    assert page.evaluate("() => window.__noNav") == 1
    # The values on the screen are the ones the server holds.
    assert value.inner_text().strip() == original
    assert page.recorded_errors == []


def test_theme_drawer_and_demo_switch_work_under_the_policy(page, server: BrowserServer, login) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue", wait_until="networkidle")
    before = page.evaluate("document.documentElement.getAttribute('data-theme')")
    page.locator("#theme-toggle").click()
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") != before
    # Open the persona menu and switch persona: a form post to the same origin.
    page.locator('[data-testid="persona-trigger"]').click()
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
