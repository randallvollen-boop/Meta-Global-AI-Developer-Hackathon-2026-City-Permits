"""The automatic linking settings of the Data Steward in a browser.

The screen reports the mode the automation really runs in, the thresholds of
the policy, a preview of the accepted source records and the two controls
that change the policy.  The tests walk the screen as the Data Steward on a
desktop, and they check that the screen still fits a phone.

The second part walks the links the automatic linking applied: the queue
holds them, the case shows the evidence, and the steward keeps or undoes the
link with a click.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02, UX-04, SEC-01
# The Data Steward reads the settings, previews the policy, activates it with
# a reason and pauses it with a reason.  Every control does what it says.

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered
from sqlalchemy import select

from acme_city.agents import linking
from acme_city.auth.context import ActorContext
from acme_city.ingestion.schemas import IngestCommand, SourceRecordCommand
from acme_city.ingestion.service import IngestionService
from acme_city.persistence.models import registry, registry_automation
from acme_city.persistence.session import SessionFactory, transaction

#: The reason the steward gives when a policy is activated.
ACTIVATE_REASON = "The applicant records wait for a master record."

#: The reason the steward gives when the automation is paused.
PAUSE_REASON = "The steward reads the first results before the work continues."

#: The reason the steward gives when an applied link is taken back.
UNDO_REASON = "The record named the wrong master record."

#: The payload of the source version the demonstration links.
LINKED_PAYLOAD = {
    "party_ref": "party_applicant_1",
    "display_name": "Demo Applicant",
    "contact_email": "demo.applicant+autolink@example.invalid",
    "contact_phone": "+1-555-0141",
    "preferred_contact": "email",
}


def open_details(page) -> None:
    """Open the disclosure of the screen."""
    page.locator('[data-testid="automation-more"] > summary').click()


def open_evidence(page) -> None:
    """Open the disclosure that holds the evidence of the link."""
    page.locator('[data-testid="case-q4-details"] > summary').click()


def apply_one_link(server: BrowserServer) -> None:
    """Prepare the demonstration: one link the automatic linking applied."""
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                registry_automation.RegistryAutomationPolicy(
                    id="policy_browser_1",
                    version=1,
                    mode="active",
                    status="active",
                    matcher_version="registry-candidates-v1",
                    thresholds={},
                    source_scopes=["applicant_profiles"],
                    reason="the demonstration applies one link",
                    recorded_by_actor_id="persona_data_steward",
                    activated_at=datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
                )
            )
        intake = IngestCommand(
            source_system_id="permitting",
            dataset_key="applicant_profiles",
            records=[
                SourceRecordCommand(
                    source_record_id="PER-AP-0001",
                    source_record_version="4",
                    payload=LINKED_PAYLOAD,
                    source_updated_at=datetime(2026, 10, 29, 12, 1, tzinfo=UTC),
                )
            ],
        )
        with transaction(factory) as session:
            service = IngestionService(session, registry_automation_mode="active")
            assert service.ingest(
                intake, ActorContext(actor_id="persona_data_steward", role_ids=frozenset())
            ).accepted == 1
        with transaction(factory) as session:
            report = linking.run_once(session)
        assert report.processed[0].decision == "auto_apply"
    finally:
        factory.dispose()


def test_the_settings_screen_says_the_automation_is_paused(
    page, server: BrowserServer, login
) -> None:
    """The default page says that automatic linking is paused."""
    login("persona_data_steward")
    response = page.goto(f"{server.base_url}/steward/automation", wait_until="load")
    assert response is not None
    assert response.status == 200
    status = page.locator('[data-testid="automation-status-line"]')
    assert status.count() == 1
    assert status.inner_text().strip() == "Automatic linking is paused"
    open_details(page)
    assert (
        page.locator('[data-testid="automation-last-run"]').inner_text().strip()
        == "No run has completed yet."
    )
    assert page.locator('[data-testid="automation-activate-form"]').count() == 1
    assert page.locator('[data-testid="automation-pause-form"]').count() == 1
    assert page.recorded_errors == []


def test_the_preview_reads_the_recorded_scores_of_the_accepted_records(
    page, server: BrowserServer, login
) -> None:
    """The preview shows the recorded score of every accepted record in scope."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward/automation", wait_until="load")
    assert page.locator('[data-testid="automation-preview"]').count() == 0
    open_details(page)
    page.locator('[data-testid="automation-preview-button"]').click()
    page.wait_for_url("**/steward/automation?preview=1")
    table = page.locator('[data-testid="automation-preview"]')
    assert table.count() == 1
    rows = table.locator("tbody tr")
    assert rows.count() > 0
    count = page.locator('[data-testid="automation-preview-count"]').inner_text()
    assert "accepted records are shown" in count
    # Every row carries a score and a reading.  A score is never a decision.
    assert table.locator('[data-label="Score"]').first.inner_text().strip() != ""
    assert "would" in table.locator('[data-label="Reading"]').first.inner_text()
    assert page.recorded_errors == []


def test_the_settings_screen_offers_only_the_mode_that_links(
    page, server: BrowserServer, login
) -> None:
    """The screen offers the mode that applies links and reviews them.

    A mode that only records suggestions is not offered: a suggestion reaches
    no steward in this release, so the screen does not show it.
    """
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward/automation", wait_until="load")
    open_details(page)
    mode = page.locator('[data-testid="automation-mode"]')
    assert mode.count() == 1
    options = mode.locator("option")
    assert options.count() == 1
    assert options.first.inner_text().strip() == "Apply eligible links"
    assert "Suggestions only" not in page.content()
    assert page.recorded_errors == []


def test_activating_a_policy_records_the_reason_and_the_version(
    page, server: BrowserServer, login
) -> None:
    """The steward activates a policy with a reason, and the page shows it."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward/automation", wait_until="load")
    open_details(page)
    form = page.locator('[data-testid="automation-activate-form"]')
    form.locator('[data-testid="automation-mode"]').select_option("active")
    form.locator('[data-testid="automation-scope-applicant_profiles"]').check()
    form.locator('[data-testid="automation-activate-reason"]').fill(ACTIVATE_REASON)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and "/ui/actions/registry.automation.activate" in response.url
    ) as posted:
        form.locator('button[type="submit"]').click()
    response = posted.value
    assert response.status == 200
    assert response.json()["status"] == "accepted"
    page.wait_for_function(
        "() => document.querySelector('[data-testid=feedback-message]') !== null"
    )
    page.reload(wait_until="load")
    open_details(page)
    policy = page.locator('[data-testid="automation-policy"]').inner_text()
    assert "Version 1" in policy
    assert "Apply eligible links" in policy
    reason = page.locator('[data-testid="automation-policy-reason"]').inner_text()
    assert ACTIVATE_REASON in reason
    scope = page.locator('[data-testid="automation-scope"]').inner_text()
    assert "Applicant contact profiles" in scope
    assert page.recorded_errors == []


def test_pausing_the_automation_records_a_paused_policy(
    page, server: BrowserServer, login
) -> None:
    """The steward pauses the automation with a reason, and the page shows it."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward/automation", wait_until="load")
    open_details(page)
    form = page.locator('[data-testid="automation-pause-form"]')
    form.locator('[data-testid="automation-pause-reason"]').fill(PAUSE_REASON)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and "/ui/actions/registry.automation.pause" in response.url
    ) as posted:
        form.locator('button[type="submit"]').click()
    response = posted.value
    assert response.status == 200
    assert response.json()["status"] == "accepted"
    page.wait_for_function(
        "() => document.querySelector('[data-testid=feedback-message]') !== null"
    )
    page.reload(wait_until="load")
    open_details(page)
    policy = page.locator('[data-testid="automation-policy"]').inner_text()
    assert "Version 1" in policy
    assert "Paused" in policy
    status = page.locator('[data-testid="automation-status-line"]').inner_text()
    assert status.strip() == "Automatic linking is paused"
    assert page.recorded_errors == []


def test_the_reviewer_may_not_open_the_settings(
    page, server: BrowserServer, login
) -> None:
    """The policy controls are the steward's alone."""
    login("persona_permit_reviewer")
    response = page.goto(f"{server.base_url}/steward/automation", wait_until="load")
    assert response is not None
    assert response.status == 403


def test_the_settings_screen_fits_a_phone(
    viewport_390, server: BrowserServer, login
) -> None:
    """At 390 pixels the screen keeps every control inside the screen."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward/automation", wait_until="load")
    assert page.viewport_size == {"width": 390, "height": 844}
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    open_details(page)
    assert_not_covered(page, page.locator('[data-testid="automation-activate"]'))
    assert_not_covered(page, page.locator('[data-testid="automation-pause"]'))
    assert page.recorded_errors == []


@pytest.mark.parametrize("path", ("/steward/automation", "/steward/automation?preview=1"))
def test_no_screen_overflows_on_a_desktop(
    page, server: BrowserServer, login, path: str
) -> None:
    """The screen and its preview stay inside a desktop window."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}{path}", wait_until="load")
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 1, (path, overflow)


# ------------------------------------------------------- the applied links


def test_the_applied_link_waits_in_the_queue(page, server: BrowserServer, login) -> None:
    """The queue holds the link the automation applied until it is reviewed."""
    apply_one_link(server)
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    row = page.locator('[data-issue-row][data-testid="automatic-link"]')
    assert row.count() == 1
    assert "PER-AP-0001" in row.inner_text()
    assert "Demo Applicant" in row.inner_text()
    assert page.recorded_errors == []


def test_the_case_shows_the_evidence_of_the_applied_link(
    page, server: BrowserServer, login
) -> None:
    """The case shows the score, the evidence and the two controls."""
    apply_one_link(server)
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    page.locator('[data-issue-row][data-testid="automatic-link"]').locator(
        '[data-testid="issue-link"]'
    ).click()
    # The evidence of the link sits behind the disclosure of the fourth question.
    open_evidence(page)
    page.wait_for_selector('[data-testid="automatic-evidence"]')
    assert page.locator('[data-testid="case-q4"]').count() == 1
    assert "0.70" in page.locator('[data-testid="case-q3"]').inner_text()
    guide = page.locator('[data-testid="steward-guide-answer"]').text_content() or ""
    assert "Review the recorded evidence or undo the link" in guide
    evidence = page.locator('[data-testid="automatic-evidence"]')
    assert evidence.count() == 1
    assert evidence.inner_text().strip() != ""
    assert page.locator('[data-testid="action-preview"]').count() == 2
    assert page.locator('details[data-action-id="registry.automation.undo"]').count() == 1
    assert page.locator('details[data-action-id="registry.automation.review"]').count() == 1
    assert page.recorded_errors == []


def test_the_steward_undoes_the_applied_link(
    page, server: BrowserServer, login, submit_action
) -> None:
    """The undo takes the link back and the queue no longer waits for it."""
    apply_one_link(server)
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    page.locator('[data-issue-row][data-testid="automatic-link"]').locator(
        '[data-testid="issue-link"]'
    ).click()
    open_evidence(page)
    page.wait_for_selector('[data-testid="automatic-evidence"]')
    message = submit_action("registry.automation.undo", {"reason": UNDO_REASON})
    assert "was taken back" in message
    # The link itself is taken back in the registry.
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            links = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "PER-AP-0001"
                )
            ).scalars().all()
            assert len(links) == 1
            assert links[0].link_status == "removed"
    finally:
        factory.dispose()
    page.goto(f"{server.base_url}/steward", wait_until="load")
    assert page.locator('[data-issue-row][data-testid="automatic-link"]').count() == 0
    page.goto(f"{server.base_url}/steward?filter=resolved", wait_until="load")
    assert page.locator('[data-issue-row][data-testid="automatic-link"]').count() == 1
    assert page.recorded_errors == []


def test_the_steward_keeps_the_applied_link(
    page, server: BrowserServer, login, submit_action
) -> None:
    """The review keeps the link and records that a person looked at it."""
    apply_one_link(server)
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    page.locator('[data-issue-row][data-testid="automatic-link"]').locator(
        '[data-testid="issue-link"]'
    ).click()
    open_evidence(page)
    page.wait_for_selector('[data-testid="automatic-evidence"]')
    message = submit_action(
        "registry.automation.review", {"note": "The master record is right."}
    )
    assert "was reviewed" in message
    page.goto(f"{server.base_url}/steward", wait_until="load")
    assert page.locator('[data-issue-row][data-testid="automatic-link"]').count() == 0
    assert page.recorded_errors == []


def test_the_reviewer_may_not_undo_an_applied_link(
    page, server: BrowserServer, login
) -> None:
    """The undo control is the grant of the Data Steward alone."""
    apply_one_link(server)
    login("persona_permit_reviewer")
    response = page.goto(f"{server.base_url}/steward", wait_until="load")
    assert response is not None
    assert response.status == 403


def test_the_applied_link_fits_a_phone(viewport_390, server: BrowserServer, login) -> None:
    """At 390 pixels the case and its controls stay inside the screen."""
    apply_one_link(server)
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    assert_no_horizontal_overflow(page)
    page.locator('[data-issue-row][data-testid="automatic-link"]').locator(
        '[data-testid="issue-link"]'
    ).click()
    open_evidence(page)
    page.wait_for_selector('[data-testid="automatic-evidence"]')
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert_not_covered(
        page, page.locator('details[data-action-id="registry.automation.undo"] summary')
    )
    assert page.recorded_errors == []


def test_the_applied_link_case_stays_inside_a_desktop_window(
    page, server: BrowserServer, login
) -> None:
    """The case of an applied link stays inside a desktop window."""
    apply_one_link(server)
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    page.locator('[data-issue-row][data-testid="automatic-link"]').locator(
        '[data-testid="issue-link"]'
    ).click()
    open_evidence(page)
    page.wait_for_selector('[data-testid="automatic-evidence"]')
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 1, overflow
    assert page.recorded_errors == []
