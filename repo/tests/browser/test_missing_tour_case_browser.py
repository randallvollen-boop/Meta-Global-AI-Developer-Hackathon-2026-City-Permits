"""The tour forgets a café copy that disappeared after the data was reset."""
# REQUIRES: UX-04

from __future__ import annotations

from conftest import BrowserServer


def test_a_missing_tour_case_clears_the_saved_tour_state(page, server: BrowserServer, login) -> None:
    """The recovery page stops a stored tour from returning to its missing copy."""
    login("persona_permit_reviewer")
    page.evaluate(
        """() => sessionStorage.setItem('acme-tour', JSON.stringify({
          active: true, index: 4, playing: true, path: 'cafe',
          caseId: 'app_judge_79750d', copy: { id: 'app_judge_79750d' }
        }))"""
    )

    response = page.goto(f"{server.base_url}/permits/app_judge_79750d", wait_until="networkidle")

    assert response is not None and response.status == 404
    assert page.locator('body[data-case-missing="true"]').count() == 1
    assert page.locator("h1").inner_text() == "This case is no longer here"
    assert page.locator('[data-testid="missing-case-start-fresh"]').inner_text() == "Start fresh"
    assert page.evaluate("() => sessionStorage.getItem('acme-tour')") is None
    assert page.recorded_errors == []
