"""The browser walkthrough of the primary chain.

The steward approves a link, the reviewer records a decision, Finance
confirms an allocation and the reviewer issues the permit.  Every step goes
through a real form of the interface, and every step survives a reload.
"""
# REQUIRES: PER-01, PER-04, PER-05, FIN-01, FIN-04, FIN-05, MDM-02, UX-04, CHG-01
# The interface performs the persisted transitions of the primary chain: the
# steward decision, the reviewer decision, the fee allocation and the
# separate issuance action.

from __future__ import annotations

import re

from conftest import BrowserServer


def approve_the_applicant_link(page, server: BrowserServer, submit_action, login) -> None:
    """Let the data steward approve the canonical link of the applicant."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="domcontentloaded")
    message = submit_action(
        "registry.propose",
        {
            "source_system_id": "permitting",
            "dataset_key": "applicant_profiles",
            "source_record_id": "PER-AP-0003",
        },
    )
    assert "candidate link" in message
    page.reload(wait_until="domcontentloaded")
    assert page.locator('[data-testid="match-proposal"]').count() >= 1

    message = submit_action(
        "registry.decide",
        {
            "source_system_id": "permitting",
            "dataset_key": "applicant_profiles",
            "source_record_id": "PER-AP-0003",
            "entity_id": "party_cedarline",
            "decision": "approve",
            "reason": "the recorded alias and the declared reference name the same party",
        },
    )
    assert "Recorded the approve decision" in message
    # Changed deliberately (steward restyle): a decided link leaves "Needs review"
    # and is listed under the Resolved filter of Data issues.
    page.goto(f"{server.base_url}/steward?filter=resolved", wait_until="domcontentloaded")
    approved = page.locator('[data-testid="crosswalk-row"][data-link-status="approved"]')
    assert approved.count() >= 1


def approve_the_contractor_link(page, server: BrowserServer, submit_action, login) -> None:
    """Let the data steward approve the canonical link of the contractor."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="domcontentloaded")
    submit_action(
        "registry.propose",
        {
            "source_system_id": "permitting",
            "dataset_key": "contractor_register",
            "source_record_id": "PER-CR-00188",
        },
    )
    submit_action(
        "registry.decide",
        {
            "source_system_id": "permitting",
            "dataset_key": "contractor_register",
            "source_record_id": "PER-CR-00188",
            "entity_id": "party_ironvale",
            "decision": "approve",
            "reason": "the registration and the declared contractor agree",
        },
    )
    # Changed deliberately (steward restyle): see above; both links are Resolved.
    page.goto(f"{server.base_url}/steward?filter=resolved", wait_until="domcontentloaded")
    approved = page.locator('[data-testid="crosswalk-row"][data-link-status="approved"]')
    assert approved.count() >= 2


def test_the_primary_chain_runs_through_the_forms_and_survives_a_reload(
    page, server: BrowserServer, login, submit_action
) -> None:
    approve_the_applicant_link(page, server, submit_action, login)
    approve_the_contractor_link(page, server, submit_action, login)

    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    message = submit_action("permit.evaluate", {"application_id": "app_synth_001"})
    assert "Checks finished" in message
    page.reload(wait_until="domcontentloaded")
    assert page.locator('[data-testid="rule-results"]').count() == 1
    assert "Passed" in page.locator('[data-testid="rule-results"]').inner_text()

    message = submit_action(
        "permit.decide",
        {
            "application_id": "app_synth_001",
            "outcome": "approved",
            "reason": "the validated inputs and the approved links support the application",
        },
    )
    assert "Recorded the reviewer decision" in message
    page.reload(wait_until="domcontentloaded")
    # The decision history is a closed disclosure; the current decision stays above it.
    page.locator('[data-testid="decision-history"] > summary').click()
    assert "approved" in page.locator('[data-testid="decision-table"]').inner_text()

    login("persona_city_administrator")
    page.goto(f"{server.base_url}/reconciliation", wait_until="domcontentloaded")
    message = submit_action(
        "finance.assess",
        {
            "application_id": "app_synth_001",
            "valuation": "50000.00",
            "reason": "the declared valuation of the application",
        },
    )
    assert "Assessed" in message
    page.reload(wait_until="domcontentloaded")
    row = page.locator(
        '[data-testid="assessment-row"][data-application-id="app_synth_001"]'
    ).first
    assessment_id = row.get_attribute("data-assessment-id")
    assert assessment_id
    assert "150.00" in row.inner_text()

    message = submit_action(
        "finance.allocate",
        {
            "payment_id": "payment_d01_settled",
            "assessment_id": assessment_id,
            "amount": "150.00",
            "currency": "USD",
            "idempotency_key": "browser-allocation-1",
            "reason": "the settled receipt covers the assessed amount",
        },
    )
    assert "Confirmed an allocation" in message
    # Changed deliberately (the reconciliation restyle): the allocations of the
    # register live with the receipt register, which has its own tab, so that
    # the register never reads as part of the selected assessment.  The
    # allocations of one assessment are shown with that assessment.
    page.goto(
        f"{server.base_url}/reconciliation?tab=receipts", wait_until="domcontentloaded"
    )
    assert page.locator('[data-testid="allocation-row"]').count() >= 1
    page.goto(f"{server.base_url}/reconciliation", wait_until="domcontentloaded")

    message = submit_action(
        "finance.reconcile",
        {
            "assessment_id": assessment_id,
            "payment_ids": "payment_d01_settled",
        },
    )
    assert "Reconciled position" in message
    page.reload(wait_until="domcontentloaded")
    row = page.locator(
        '[data-testid="assessment-row"][data-application-id="app_synth_001"]'
    ).first
    assert "0.00" in row.inner_text()
    assert row.get_attribute("data-status") in {"reconciled", "closed", "exact"}

    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    message = submit_action(
        "permit.issue",
        {
            "application_id": "app_synth_001",
            "command_key": "issue-browser-1",
            "reason": "the finance position is exact",
        },
    )
    assert "Issued the simulated permit" in message
    permit_number = re.search(r"ACME-2026-\d+", message)
    assert permit_number is not None

    page.reload(wait_until="domcontentloaded")
    issued = page.locator('[data-testid="value-issued"]').first.inner_text()
    assert permit_number.group(0) in issued
    assert page.locator('[data-testid="feedback-message"]').inner_text().strip() != ""


def test_an_identical_issuance_retry_returns_the_original_permit(
    page, server: BrowserServer, login, submit_action
) -> None:
    approve_the_applicant_link(page, server, submit_action, login)
    approve_the_contractor_link(page, server, submit_action, login)

    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    submit_action("permit.evaluate", {"application_id": "app_synth_001"})
    page.reload(wait_until="domcontentloaded")
    submit_action(
        "permit.decide",
        {
            "application_id": "app_synth_001",
            "outcome": "approved",
            "reason": "the validated inputs and the approved links support the application",
        },
    )

    login("persona_city_administrator")
    page.goto(f"{server.base_url}/reconciliation", wait_until="domcontentloaded")
    submit_action(
        "finance.assess",
        {
            "application_id": "app_synth_001",
            "valuation": "50000.00",
            "reason": "the declared valuation of the application",
        },
    )
    page.reload(wait_until="domcontentloaded")
    assessment_id = page.locator(
        '[data-testid="assessment-row"][data-application-id="app_synth_001"]'
    ).first.get_attribute("data-assessment-id")
    submit_action(
        "finance.allocate",
        {
            "payment_id": "payment_d01_settled",
            "assessment_id": assessment_id,
            "amount": "150.00",
            "currency": "USD",
            "idempotency_key": "browser-allocation-retry",
            "reason": "the settled receipt covers the assessed amount",
        },
    )
    submit_action(
        "finance.reconcile",
        {"assessment_id": assessment_id, "payment_ids": "payment_d01_settled"},
    )

    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    first = submit_action(
        "permit.issue",
        {
            "application_id": "app_synth_001",
            "command_key": "issue-browser-retry",
            "reason": "the finance position is exact",
        },
    )
    number = re.search(r"ACME-2026-\d+", first)
    assert number is not None
    # The same command key with the same expected versions is the same command:
    # the server answers with the permit it already issued.
    second = submit_action(
        "permit.issue",
        {
            "application_id": "app_synth_001",
            "command_key": "issue-browser-retry",
            "reason": "the finance position is exact",
        },
    )
    assert number.group(0) in second
    page.reload(wait_until="domcontentloaded")
    issued = page.locator('[data-testid="value-issued"]').first.inner_text()
    assert number.group(0) in issued
