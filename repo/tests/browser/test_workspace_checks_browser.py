"""Run application checks shows the result, and a second run does not duplicate it."""
# REQUIRES: UX-01, UX-02
# The Review tab shows the summary, each rule and its citation, and the next
# step. A second press on an unchanged revision keeps the same evaluation.

from __future__ import annotations

from sqlalchemy import func, select

from conftest import BrowserServer

from acme_city.persistence.models import audit, permit
from acme_city.persistence.session import SessionFactory

CASE = "app_synth_001"


def no_sideways_scroll(page) -> bool:
    return page.evaluate(
        "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )


def _counts(server: BrowserServer) -> tuple[int, int, int]:
    """Return evaluation rows, application.evaluate audits, and accepted clicks."""
    factory = SessionFactory(server.settings.database_url)
    try:
        with factory() as session:
            evaluations = session.execute(
                select(func.count())
                .select_from(permit.Evaluation)
                .where(permit.Evaluation.application_id == CASE)
            ).scalar_one()
            service_audits = session.execute(
                select(func.count())
                .select_from(audit.AuditEvent)
                .where(audit.AuditEvent.action == "application.evaluate")
            ).scalar_one()
            clicks = session.execute(
                select(func.count())
                .select_from(audit.AuditEvent)
                .where(
                    audit.AuditEvent.action == "ui.permit.evaluate",
                    audit.AuditEvent.outcome == "accepted",
                )
            ).scalar_one()
    finally:
        factory.dispose()
    return int(evaluations), int(service_audits), int(clicks)


def test_run_checks_shows_the_result_and_a_second_press_keeps_it(
    page, server: BrowserServer, login, submit_action
) -> None:
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/{CASE}", wait_until="domcontentloaded")
    assert "Run application checks" in page.locator(
        "details[data-action-id='permit.evaluate']"
    ).inner_text()

    message = submit_action("permit.evaluate", {"application_id": CASE})
    assert message.startswith("Checks finished:")
    assert "record the decision" not in message
    assert "still prevent" in message

    summary = page.locator("[data-testid='checks-result-summary']")
    expect_text = summary.inner_text().strip()
    rows = page.locator("[data-testid='check-result']")
    count = rows.count()
    assert count >= 1
    assert expect_text == ("The check passed" if count == 1 else f"All {count} checks passed")
    for index in range(count):
        citation = rows.nth(index).locator("[data-testid='check-citation']")
        assert citation.inner_text().strip()
        assert rows.nth(index).locator("[data-testid='check-plain']").inner_text().strip()

    next_button = page.locator("[data-testid='checks-next-button']")
    assert next_button.inner_text().strip() == "Review the blockers"
    next_button.click()
    assert page.evaluate("() => location.hash") == "#application-blockers"
    page.locator("#application-blockers").scroll_into_view_if_needed()

    run_again = page.locator("details[data-action-id='permit.evaluate']")
    assert "Run checks again" in run_again.inner_text()
    assert page.locator("[data-testid='checks-last-run']").inner_text().strip().startswith(
        "Last run "
    )
    evaluations, service_audits, clicks = _counts(server)
    assert evaluations == 1
    assert service_audits == 1
    assert clicks == 1

    again = submit_action("permit.evaluate", {"application_id": CASE})
    assert again.startswith("These checks already ran on this revision:")
    assert "record the decision" not in again
    evaluations, service_audits, clicks = _counts(server)
    assert evaluations == 1
    assert service_audits == 1
    assert clicks == 2
    assert page.locator("[data-testid='checks-result-summary']").inner_text().strip() == expect_text

    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(f"{server.base_url}/permits/{CASE}", wait_until="domcontentloaded")
    assert page.locator("[data-testid='checks-result-summary']").is_visible()
    assert page.locator("[data-testid='checks-next-button']").is_visible()
    assert page.locator("[data-testid='checks-last-run']").is_visible()
    assert no_sideways_scroll(page)
    page.locator("[data-testid='checks-next-button']").click()
    assert page.evaluate("() => location.hash") == "#application-blockers"
    assert page.recorded_errors == []
