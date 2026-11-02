"""The reviewer reads agent tags on the queue and filters to one of them.

The cases are written into the isolated server's own database. The seeded
demonstration cases stay as they were.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.ids import new_id
from acme_city.permits.schemas import SubmitApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole
from acme_city.persistence.session import SessionFactory, transaction

from conftest import BrowserServer

DENY = "SYN-APP-801"
APPROVE = "SYN-APP-802"
EARLY = "SYN-APP-803"
DENY_REASON = "Rule(s) DF-1 fail, so the agent recommends denial."


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


def _seed(server: BrowserServer) -> None:
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            actor = _context(session, "persona_data_steward")
            permits = PermitService(session)
            when = datetime(2026, 10, 1, tzinfo=UTC)

            def submit(number: str, name: str, status: str):
                view = permits.submit(
                    SubmitApplicationCommand(
                        permit_type_key="com_ti",
                        source_application_number=number,
                        facts={
                            "project_description": "A fictional fence",
                            "applicant_name": name,
                            "submitted_site_text": f"1 {name} Lane, ACME City",
                        },
                    ),
                    actor,
                )
                row = session.get(permit.Application, view.application_id)
                assert row is not None
                row.status = status
                return row

            denied = submit(DENY, "Deny Builder", "ready_for_review")
            approved = submit(APPROVE, "Approve Builder", "ready_for_review")
            submit(EARLY, "Early Builder", "needs_information")
            session.add(
                permit.Recommendation(
                    id=new_id("rec"),
                    application_id=denied.id,
                    proposed_outcome="deny",
                    status="pending",
                    rationale=DENY_REASON,
                    created_at=when,
                )
            )
            session.add(
                permit.Recommendation(
                    id=new_id("rec"),
                    application_id=approved.id,
                    proposed_outcome="approve",
                    status="pending",
                    rationale="Every applicable rule passes, so the agent recommends approval.",
                    created_at=when,
                )
            )
            early = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == EARLY
                )
            ).scalar_one()
            session.add(
                permit.ApplicationFinding(
                    id=new_id("finding"),
                    correlation_id=early.correlation_id,
                    application_id=early.id,
                    finding_type="missing_document",
                    message="The site plan is missing.",
                    severity="block",
                    state="current",
                    revision_number=early.revision,
                    version=1,
                )
            )
    finally:
        factory.dispose()


def test_tag_chips_filter_the_queue(page, server: BrowserServer, login) -> None:
    _seed(server)
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/queue?view=all", wait_until="domcontentloaded")
    tags = page.locator('[data-testid="queue-tag"]')
    assert tags.filter(has_text="Agent: deny").count() == 1
    assert tags.filter(has_text="Agent: approve").count() == 1
    assert tags.filter(has_text="Intake: early resolution").count() == 1
    deny = tags.filter(has_text="Agent: deny")
    assert deny.get_attribute("title") == DENY_REASON
    page.locator('[data-testid="queue-tag-filter"][data-tag="agent_deny"]').click()
    page.wait_for_url("**tag=agent_deny**")
    assert page.locator('[data-testid="queue-item"]').count() == 1
    assert page.locator('[data-testid="queue-item"]', has_text=DENY).count() == 1
    assert page.locator('[data-testid="queue-item"]', has_text=APPROVE).count() == 0

    page.goto(f"{server.base_url}/queue/review", wait_until="domcontentloaded")
    review_tags = page.locator('[data-testid="queue-tag"]')
    assert review_tags.filter(has_text="Agent: deny").count() == 1
    assert review_tags.filter(has_text="Agent: approve").count() == 1
    assert review_tags.filter(has_text="Intake: early resolution").count() == 0
    assert page.locator('[data-testid="review-row"]', has_text=DENY).count() == 1
    assert page.recorded_errors == []
