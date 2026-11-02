"""The review queue shows Stage and Next action, and a phone stacks the row.

The two cases are written into the isolated server's own database. The
seeded demonstration cases stay as they were.
"""

from __future__ import annotations

from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.permits.schemas import SubmitApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole
from acme_city.persistence.session import SessionFactory, transaction

from conftest import BrowserServer


def no_sideways_scroll(page) -> bool:
    return page.evaluate(
        "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )


def _context(session, actor_id: str) -> ActorContext:
    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


def _seed_two_actions(server: BrowserServer) -> None:
    """Put two in-review cases with different next actions into the server database."""
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            actor = _context(session, "persona_data_steward")
            permits = PermitService(session)
            flagged = permits.submit(
                SubmitApplicationCommand(
                    permit_type_key="com_ti",
                    facts={
                        "project_description": "A flagged fence",
                        "submitted_site_text": "910 Queue Stage Lane, ACME City",
                    },
                ),
                actor,
            )
            flagged_row = session.get(permit.Application, flagged.application_id)
            assert flagged_row is not None
            flagged_row.status = "ready_for_review"
            flagged_row.presubmit_override = {"reason": "Submitted anyway for the queue."}
            plain = permits.submit(
                SubmitApplicationCommand(
                    permit_type_key="com_ti",
                    facts={
                        "project_description": "A plain fence",
                        "submitted_site_text": "920 Queue Stage Lane, ACME City",
                    },
                ),
                actor,
            )
            plain_row = session.get(permit.Application, plain.application_id)
            assert plain_row is not None
            plain_row.status = "ready_for_review"
    finally:
        factory.dispose()


def test_stage_and_next_action_filter_and_fit_on_a_phone(
    page, server: BrowserServer, login
) -> None:
    _seed_two_actions(server)
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/queue/review", wait_until="domcontentloaded")
    for heading in ("Reference", "Type", "Stage", "Next action", "Recommendation", "Age"):
        assert page.get_by_role("columnheader", name=heading, exact=True).is_visible()
    stage_labels = page.locator(
        '[data-testid="review-stage-label"]', has_text="Checks (3 of 6)"
    )
    assert stage_labels.count() >= 2
    issues = page.locator('[data-testid="review-row"][data-next="submitted_issues"]')
    checks = page.locator('[data-testid="review-row"][data-next="needs_checks"]')
    assert issues.count() >= 1
    assert checks.count() >= 1
    chip = page.locator('[data-testid="next-action-filter"][data-next="submitted_issues"]')
    count = int(chip.locator('[data-testid="next-action-count"]').inner_text())
    assert count == issues.count()
    assert count < page.locator('[data-testid="review-row"]').count()
    chip.click()
    page.wait_for_url("**next_action=submitted_issues**")
    assert page.locator('[data-testid="review-row"]').count() == count
    assert page.locator('[data-testid="review-row"][data-next="needs_checks"]').count() == 0
    assert page.locator('[data-testid="review-next-action"]').first.inner_text() == (
        "Submitted with known issues"
    )

    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(f"{server.base_url}/queue/review", wait_until="domcontentloaded")
    assert page.locator('[data-testid="review-stage"]').first.is_visible()
    assert page.locator('[data-testid="review-next-action"]').first.is_visible()
    assert no_sideways_scroll(page)
    fits = page.evaluate(
        """() => {
            const wrap = document.querySelector('[data-testid="review-table-wrap"]');
            const row = document.querySelector('[data-testid="review-row"]');
            const head = document.querySelector('.review-queue-table thead');
            return wrap.scrollWidth <= wrap.clientWidth + 1
                && getComputedStyle(row).display === 'block'
                && getComputedStyle(head).display === 'none';
        }"""
    )
    assert fits
    assert page.recorded_errors == []
