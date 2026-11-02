"""The four P3c screens in the browser, as the City Administrator.

Every screen must render without a page error and fit a phone, the help button
and the audit-event drawer must work by keyboard, a run of the checks must show
its eight results, and a help request answered by the Administrator must reach
the applicant.
"""
# REQUIRES: UX-01, UX-02, UX-03, PER-04

from __future__ import annotations

import sys
from pathlib import Path

from conftest import (
    BrowserServer,
    assert_no_horizontal_overflow,
    assert_not_covered,
    open_the_last_action,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from p3c_support import seed_help_request  # noqa: E402

SCREENS = (
    ("/ops/dashboard", "Operations"),
    ("/ops/audit", "Audit log"),
    ("/ops/support", "Support"),
    ("/ops/checks", "Checks"),
)


def overflow(page) -> int:
    return page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")


def test_the_screens_render_and_fit_a_phone_and_a_desktop(page, server: BrowserServer, login) -> None:
    login("persona_city_administrator")
    for width, height in ((1280, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        for path, heading in SCREENS:
            response = page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
            assert response is not None and response.status == 200, path
            assert page.locator("h1").first.inner_text() == heading, path
            assert overflow(page) <= 1, (width, path, overflow(page))
    assert page.recorded_errors == []


def test_the_help_button_opens_and_closes_by_keyboard(page, server: BrowserServer, login) -> None:
    login("persona_city_administrator")
    for path, _ in SCREENS:
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        button = page.locator('[data-testid="ui-help"]').first
        button.focus()
        page.keyboard.press("Enter")
        drawer = page.locator('[data-testid="ui-drawer"]')
        drawer.wait_for(state="visible")
        assert "What you can do here" in drawer.inner_text() or "can do" in drawer.inner_text().lower()
        page.keyboard.press("Escape")
        drawer.wait_for(state="hidden")
    assert page.recorded_errors == []


def test_the_dashboard_prints_six_figures_with_definitions_and_three_charts(page, server: BrowserServer, login) -> None:
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/ops/dashboard", wait_until="domcontentloaded")
    assert page.locator('[data-testid="ops-figure"]').count() == 6
    for definition in page.locator('[data-testid="ops-figure-definition"]').all_inner_texts():
        assert len(definition) > 20
    assert page.locator("svg.ops-chart").count() >= 1
    assert page.locator('[data-testid="chart-status-table"]').count() == 1


def test_the_breakdowns_keep_the_table_visible_and_the_chart_closed(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    # Changed deliberately (demo polish, AD3): the data table stays visible
    # and the chart stays closed until its summary is opened, on both sizes.
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{server.base_url}/ops/dashboard", wait_until="domcontentloaded")
    assert not page.locator('[data-testid="chart-status-chart"] svg').is_visible()
    assert page.locator('[data-testid="chart-status-table"]').is_visible()
    assert page.locator('[data-testid="chart-channel-chart"]').count() == 1
    assert page.locator('[data-testid="chart-channel-table"]').count() == 1

    # A phone shows the same table and keeps the chart in its disclosure.
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/ops/dashboard", wait_until="domcontentloaded")
    assert_no_horizontal_overflow(page)
    assert page.locator('[data-testid="chart-status-table"]').is_visible()
    assert not page.locator('[data-testid="chart-status-chart"] svg').is_visible()

    # The chart keeps its own size on a phone, so no label of it is shrunk.
    page.locator('[data-testid="chart-status-chart"] summary').click()
    chart = page.locator('[data-testid="chart-status-chart"] svg')
    assert chart.is_visible()
    box = chart.bounding_box()
    assert box is not None and box["width"] == 480, box
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


def test_the_dashboard_fits_a_phone_and_keeps_the_figures_readable(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/ops/dashboard", wait_until="domcontentloaded")
    assert_no_horizontal_overflow(page)

    # The scope of the numbers comes first, then the two groups.
    assert page.locator('[data-testid="ops-scope-statement"]').is_visible()
    assert page.locator('[data-testid="ops-figure-group"]').count() == 2
    assert page.locator('[data-testid="ops-figure"]').count() == 6
    # The figures keep their definitions on a phone.
    for definition in page.locator('[data-testid="ops-figure-definition"]').all_inner_texts():
        assert len(definition) > 20

    # Neither the mobile bar nor the demo switch covers the scope.
    assert_not_covered(page, page.locator('[data-testid="persona-trigger"]'))
    assert_not_covered(page, page.locator('[data-testid="ops-scope-statement"]'))
    assert page.recorded_errors == []


def test_run_checks_shows_eight_results_and_the_feedback(page, server: BrowserServer, login, open_last_action) -> None:
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/ops/checks", wait_until="domcontentloaded")
    assert page.locator('[data-testid="checks-result"]').count() == 0
    page.locator('[data-testid="checks-run"]').click()
    page.wait_for_selector('[data-testid="checks-result"]')
    assert page.locator('[data-testid="check-row"]').count() == 8
    assert "not applicable (historical seed)" in page.locator('[data-testid="checks-table"]').inner_text()
    open_last_action()
    assert page.locator('[data-testid="feedback-message"]').inner_text().startswith("Ran the checks")
    assert page.recorded_errors == []


def test_the_checks_screen_shows_the_result_first_and_fits_a_phone(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/ops/checks", wait_until="domcontentloaded")
    page.locator('[data-testid="checks-run"]').click()
    page.wait_for_selector('[data-testid="checks-result"]')
    assert_no_horizontal_overflow(page)

    # The result comes before the results themselves.
    order = page.evaluate(
        "() => ['checks-result', 'checks-counts', 'checks-table', 'checks-details'].map("
        "(key) => document.querySelector(`[data-testid=${key}]`)"
        ".getBoundingClientRect().top)"
    )
    assert order == sorted(order), order
    # The counts are named and the eight results keep their reasons.
    counts = [
        int(
            page.locator(f'[data-testid="checks-count-{key}"]').inner_text().strip()
        )
        for key in ("pass", "fail", "na")
    ]
    assert sum(counts) == 8
    assert page.locator('[data-testid="check-row"]').count() == 8

    # Neither the mobile bar nor the demo switch covers the controls.
    assert_not_covered(page, page.locator('[data-testid="persona-trigger"]'))
    assert_not_covered(page, page.locator('[data-testid="checks-run"]'))
    assert page.recorded_errors == []


def test_the_audit_log_filters_and_opens_an_event_drawer(page, server: BrowserServer, login) -> None:
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/ops/checks", wait_until="domcontentloaded")
    page.locator('[data-testid="checks-run"]').click()
    page.wait_for_selector('[data-testid="checks-result"]')
    page.goto(f"{server.base_url}/ops/audit", wait_until="domcontentloaded")
    page.locator('[data-testid="audit-filter-actor-type"]').select_option("person")
    page.locator('[data-testid="audit-filter-apply"]').click()
    page.wait_for_url("**/ops/audit?actor_type=person**")
    assert page.locator('[data-testid="audit-row"]').count() >= 1
    assert all(t == "person" for t in page.locator('[data-testid="audit-actor-type"]').all_inner_texts())
    link = page.locator('[data-detail-kind="audit-event"]').first
    link.focus()
    page.keyboard.press("Enter")
    drawer = page.locator('[data-testid="ui-drawer"]')
    drawer.wait_for(state="visible")
    assert "Correlation id" in drawer.inner_text()
    page.keyboard.press("Escape")
    drawer.wait_for(state="hidden")
    assert page.recorded_errors == []


def test_the_administrator_answers_and_the_applicant_reads_the_reply(browser, server: BrowserServer) -> None:
    made = seed_help_request(server.settings, application_id="app_d05", question="BROWSER-QUESTION-7781")

    def sign_in(actor_id: str, landing: str):
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
        page.locator(f'button[data-persona="{actor_id}"]').click()
        page.wait_for_url(f"{server.base_url}{landing}")
        return context, page

    # Changed deliberately (the City Administrator restyle): the Administrator lands on /overview.
    admin_context, admin = sign_in("persona_city_administrator", "/overview")
    try:
        admin.goto(f"{server.base_url}/ops/support?request={made['request_id']}", wait_until="domcontentloaded")
        assert "BROWSER-QUESTION-7781" in admin.locator('[data-testid="support-requests"]').inner_text()
        admin.locator('[data-testid="help-reply"]').fill("Your review has not started; it is next in line.")
        admin.locator('[data-testid="help-answer"]').click()
        admin.wait_for_function(
            "() => { const region = document.querySelector('[data-testid=feedback-message]');"
            " return region !== null && region.textContent.trim() === 'Answered the help request.'; }"
        )
        open_the_last_action(admin)
        assert admin.locator('[data-testid="feedback-message"]').inner_text() == "Answered the help request."
    finally:
        admin_context.close()
    applicant_context, applicant = sign_in("persona_applicant", "/city/")
    try:
        applicant.goto(f"{server.base_url}/apply/track?ref=SYN-APP-005", wait_until="domcontentloaded")
        assert "Your review has not started; it is next in line." in applicant.inner_text("body")
    finally:
        applicant_context.close()


def test_a_support_case_is_recorded_and_listed(page, server: BrowserServer, login) -> None:
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/ops/support", wait_until="domcontentloaded")
    # Changed deliberately (demo polish, AD3): record assistance is closed.
    page.locator('[data-testid="support-record"] > summary').click()
    page.locator('[data-testid="case-channel"]').select_option("counter")
    page.locator('[data-testid="case-summary"]').fill("A visitor asked how fences are measured.")
    page.locator('[data-testid="case-record"]').click()
    page.locator('[data-testid="support-record"] > summary').click()
    page.wait_for_selector('[data-testid="support-case-row"]')
    assert "A visitor asked how fences are measured." in page.locator('[data-testid="support-cases"]').inner_text()
    assert page.recorded_errors == []
