"""Each workspace section collapses, and the current step starts open."""
# REQUIRES: UX-01, UX-02
# A section opens and closes from the pointer and the keyboard. The checks
# start open. After a blocked run the issues open too. An issued permit
# opens the permit section. A reload does not keep a section the person opened.

from __future__ import annotations

from conftest import BrowserServer

CASE = "app_synth_001"
ISSUED = "app_d07"

REVIEW_SECTIONS = (
    "case-pipeline",
    "responsibility-panel",
    "next-action",
    "issue-list-section",
    "ai-section",
    "application-checks",
    "agent-more",
    "stage-decision",
    "empty-stages-section",
    "corrections-more",
    "review-actions",
    "more-actions",
    "fee-preview",
)


def no_sideways_scroll(page) -> bool:
    return page.evaluate(
        "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )


def _toggle(page, testid: str) -> None:
    section = page.locator(f'[data-testid="{testid}"]')
    summary = page.locator(f'[data-testid="{testid}"] > summary')
    assert summary.is_visible(), testid
    was_open = section.get_attribute("open") is not None
    summary.click()
    assert (section.get_attribute("open") is not None) is not was_open, testid
    summary.click()
    assert (section.get_attribute("open") is not None) is was_open, testid


def test_sections_start_open_for_the_current_step_and_collapse(
    page, server: BrowserServer, login, submit_action
) -> None:
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/{CASE}", wait_until="domcontentloaded")
    assert page.locator('[data-testid="application-checks"]').get_attribute("open") is not None
    assert page.locator('[data-testid="next-action"]').get_attribute("open") is not None
    assert page.locator('[data-testid="evaluation-empty"]').is_visible()
    assert page.locator('[data-testid="stage-decision"]').get_attribute("open") is None
    assert page.locator('[data-testid="decision-empty"]').is_hidden()
    assert page.locator('[data-testid="issue-list-section"]').get_attribute("open") is None
    assert page.locator('[data-testid="review-actions"]').get_attribute("open") is None
    for testid in REVIEW_SECTIONS:
        _toggle(page, testid)
    issues = page.locator('[data-testid="issue-list-section"]')
    page.locator('[data-testid="issue-list-section"] > summary').focus()
    page.keyboard.press("Enter")
    assert issues.get_attribute("open") is not None
    assert page.locator('[data-testid="outstanding-issues"]').is_visible()
    page.keyboard.press("Enter")
    assert issues.get_attribute("open") is None
    page.reload(wait_until="domcontentloaded")
    assert page.locator('[data-testid="issue-list-section"]').get_attribute("open") is None
    assert page.locator('[data-testid="application-checks"]').get_attribute("open") is not None
    submit_action("permit.evaluate", {})
    # The result is painted when the page is read again after the action.
    page.locator('[data-testid="checks-result-summary"]').wait_for(state="visible")
    assert page.locator('[data-testid="application-checks"]').get_attribute("open") is not None
    assert page.locator('[data-testid="issue-list-section"]').get_attribute("open") is not None
    assert page.locator('[data-testid="outstanding-issues"]').is_visible()
    assert page.locator('[data-testid="checks-result-summary"]').is_visible()
    assert page.locator('[data-testid="stage-decision"]').get_attribute("open") is None
    page.locator('[data-testid="agent-more"] > summary').click()
    intake = page.locator('[data-testid="rerun-intake"]')
    adjudication = page.locator('[data-testid="rerun-adjudication"]')
    assert intake.is_disabled()
    assert adjudication.is_disabled()
    assert page.locator('[data-testid="rerun-locked"]').is_visible()
    assert "awake" in page.locator('[data-testid="rerun-locked"]').inner_text()
    page.set_viewport_size({"width": 390, "height": 800})
    assert no_sideways_scroll(page)
    page.locator('[data-testid="stage-decision"] > summary').click()
    assert no_sideways_scroll(page)
    for tab, sections in (
        ("documents", ("submission-section", "documents-section", "documents-more")),
        ("people", ("people-more",)),
        ("activity", ("activity-comments", "activity-history")),
    ):
        page.locator(f"#tab-{tab}").click()
        for testid in sections:
            _toggle(page, testid)
        assert no_sideways_scroll(page), tab
    page.goto(f"{server.base_url}/permits/{ISSUED}", wait_until="domcontentloaded")
    assert page.locator('[data-testid="stage-permit"]').get_attribute("open") is not None
    assert page.locator('[data-testid="value-issued"]').is_visible()
    assert page.locator('[data-testid="stage-decision"]').get_attribute("open") is None
    assert page.locator('[data-testid="application-checks"]').get_attribute("open") is None
    assert no_sideways_scroll(page)
    assert page.recorded_errors == []
