"""The reviewer searches the queue and opens the one matching case.

The case is written into the isolated server's own database. The seeded
demonstration cases stay as they were.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.permits.schemas import SubmitApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole
from acme_city.persistence.session import SessionFactory, transaction

from conftest import BrowserServer

TARGET = "SYN-APP-617"


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
            permits = PermitService(session)
            view = permits.submit(
                SubmitApplicationCommand(
                    permit_type_key="com_ti",
                    source_application_number=TARGET,
                    facts={
                        "project_description": "A fictional fence",
                        "applicant_name": "Helena Moss",
                        "submitted_site_text": "18 Quill Court, ACME City",
                    },
                ),
                _context(session, "persona_data_steward"),
            )
            row = session.get(permit.Application, view.application_id)
            assert row is not None
            row.status = "ready_for_review"
    finally:
        factory.dispose()


def _search(page, text: str) -> None:
    page.locator('[data-testid="queue-find-input"]').fill(text)
    page.locator('[data-testid="queue-find-submit"]').click()
    page.wait_for_url("**q=617**")


def _from_path(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return query.get("from", [""])[0]


def test_search_opens_the_one_matching_case(page, server: BrowserServer, login) -> None:
    _seed(server)
    login("persona_permit_reviewer")

    page.goto(f"{server.base_url}/queue/review", wait_until="domcontentloaded")
    _search(page, "617")
    assert page.locator('[data-testid="queue-find-summary"]').inner_text().startswith(
        "1 match for 617"
    )
    row = page.locator('[data-testid="review-row"]', has_text=TARGET)
    assert row.count() == 1
    page.locator('[data-testid="queue-find-open"]').click()
    page.wait_for_url("**/permits/**")
    opened = urlparse(page.url)
    assert opened.path.startswith("/permits/")
    came_from = _from_path(page.url)
    assert came_from.startswith("/queue/review")
    assert "q=617" in came_from
    assert TARGET in page.locator('[data-testid="case-reference"]').inner_text()

    page.goto(f"{server.base_url}/queue?view=all", wait_until="domcontentloaded")
    _search(page, "617")
    assert page.locator('[data-testid="queue-item"]', has_text=TARGET).count() == 1
    page.locator('[data-testid="queue-find-open"]').click()
    page.wait_for_url("**/permits/**")
    work_from = _from_path(page.url)
    assert work_from.startswith("/queue?")
    assert "q=617" in work_from
    assert TARGET in page.locator('[data-testid="case-reference"]').inner_text()
    assert page.recorded_errors == []
