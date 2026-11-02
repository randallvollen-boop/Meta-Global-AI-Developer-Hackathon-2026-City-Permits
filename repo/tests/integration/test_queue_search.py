"""Search on the work queue and the review queue.

The search is a query-string value. It runs on the full list and only then
keeps one page, so a match past the first page is still found. The seeded
cases stay as they were. The extra cases exist only in this test database.
"""

from __future__ import annotations

import html
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.permits.router import router as permit_router
from acme_city.permits.schemas import SubmitApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.queue_find import PAGE_SIZE
from acme_city.ui.router import router as ui_router

REVIEWER = "persona_permit_reviewer"
STEWARD = "persona_data_steward"
TARGET = "SYN-APP-617"
NEIGHBOR = "SYN-APP-200"


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


def _submit(
    permits: PermitService,
    session,
    actor: ActorContext,
    number: str,
    name: str,
    site: str,
):
    view = permits.submit(
        SubmitApplicationCommand(
            permit_type_key="com_ti",
            source_application_number=number,
            facts={
                "project_description": "A fictional fence",
                "applicant_name": name,
                "submitted_site_text": site,
            },
        ),
        actor,
    )
    row = session.get(permit.Application, view.application_id)
    assert row is not None
    row.status = "ready_for_review"
    return row


def _seed(settings: Settings) -> None:
    """Put enough in-review cases that SYN-APP-617 sits past the first page."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            actor = _context(session, STEWARD)
            permits = PermitService(session)
            for number in range(100, 124):
                _submit(
                    permits,
                    session,
                    actor,
                    f"SYN-APP-{number}",
                    "Filler Applicant",
                    "10 Filler Lane, ACME City",
                )
            _submit(
                permits,
                session,
                actor,
                NEIGHBOR,
                "Other Builder",
                "19 Quill Court, ACME City",
            )
            target = _submit(
                permits,
                session,
                actor,
                TARGET,
                "Helena Moss",
                "18 Quill Court, ACME City",
            )
            target.presubmit_override = {"reason": "Submitted anyway for the queue."}
    finally:
        factory.dispose()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    directory = tmp_path_factory.mktemp("queue-search")
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{directory / 'queue-search.db'}",
            "ACME_SECRET_KEY": "queue-search-test-secret-value",
        },
        key_file=directory / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                DemoEnvironment(
                    id="demo_environment_local",
                    environment_id=ENVIRONMENT_ID,
                    fictional_demo=True,
                    fixture_version=bundle.fixture_version,
                    label="local fictional demonstration",
                )
            )
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    finally:
        factory.dispose()
    _seed(settings)
    app = create_app(settings)
    app.include_router(ui_router)
    app.include_router(permit_router)
    with TestClient(app) as test_client:
        assert test_client.post(
            "/api/session/select", json={"actor_id": REVIEWER}
        ).status_code == 200
        yield test_client


def _rows(page: str, test_id: str) -> int:
    return page.count(f'data-testid="{test_id}"')


def _clear_href(page: str) -> str:
    match = re.search(r'href="([^"]+)" data-testid="queue-find-clear"', page)
    assert match is not None
    return html.unescape(match.group(1))


def _work_row(page: str, reference: str) -> str:
    rows = re.findall(r'<tr class="row" data-testid="queue-item".*?</tr>', page, re.S)
    return next(row for row in rows if f">{reference}<" in row)


def test_a_number_finds_the_case_past_the_first_page(client: TestClient) -> None:
    first = client.get("/queue/review").text
    assert TARGET not in first
    assert _rows(first, "review-row") == PAGE_SIZE
    assert 'data-testid="queue-pager"' in first
    assert 'data-testid="queue-find"' in first
    second = client.get("/queue/review?page=2").text
    assert TARGET in second

    found = client.get("/queue/review?q=617").text
    assert TARGET in found
    assert "1 match for 617" in found
    assert 'data-testid="queue-find-open"' in found
    assert "from=" in found
    assert _clear_href(found) == "/queue/review"
    full = client.get("/queue/review?q=SYN-APP-617").text
    assert "1 match for SYN-APP-617" in full and TARGET in full
    folded = client.get("/queue/review?q=syn-app-617").text
    assert "1 match for syn-app-617" in folded and TARGET in folded

    work_first = client.get("/queue?view=all").text
    assert TARGET not in work_first
    assert 'data-testid="queue-pager"' in work_first
    work = client.get("/queue?view=all&q=617").text
    assert TARGET in work
    assert "1 match for 617" in work
    assert 'data-testid="queue-find-open"' in work
    assert "from=" in work
    assert "q=" not in _clear_href(work)


def test_search_matches_the_name_and_the_address(client: TestClient) -> None:
    by_name = client.get("/queue/review?q=HELENA").text
    assert TARGET in by_name
    assert NEIGHBOR not in by_name
    assert "1 match for HELENA" in by_name
    by_address = client.get("/queue/review?q=18+Quill").text
    assert TARGET in by_address
    assert NEIGHBOR not in by_address
    assert "1 match for 18 Quill" in by_address

    work_name = client.get("/queue?view=all&q=Helena+Moss").text
    assert TARGET in work_name
    assert "1 match for Helena Moss" in work_name
    work_address = client.get("/queue?view=all&q=18+quill").text
    assert TARGET in work_address
    assert NEIGHBOR not in work_address


def test_search_combines_with_a_chip(client: TestClient) -> None:
    both = client.get("/queue/review?q=quill").text
    assert TARGET in both and NEIGHBOR in both
    assert "2 matches for quill" in both
    assert 'data-testid="queue-find-open"' not in both

    flagged = client.get("/queue/review?q=quill&next_action=submitted_issues").text
    assert TARGET in flagged
    assert NEIGHBOR not in flagged
    assert "1 match for quill" in flagged
    assert 'data-testid="queue-find-open"' in flagged
    clear = _clear_href(flagged)
    assert "q=" not in clear
    assert "next_action=submitted_issues" in clear

    checks = client.get("/queue/review?q=quill&next_action=needs_checks").text
    assert NEIGHBOR in checks
    assert TARGET not in checks

    work = client.get("/queue?view=all&q=617").text
    bucket = re.search(r'data-bucket="(\w+)"', _work_row(work, TARGET))
    assert bucket is not None
    kept = client.get(f"/queue?view=all&focus={bucket.group(1)}&q=617").text
    assert TARGET in kept
    other = "issued" if bucket.group(1) != "issued" else "checks"
    missed = client.get(f"/queue?view=all&focus={other}&q=617").text
    assert "No match for 617." in missed
    assert TARGET not in missed


def test_a_search_with_no_match_says_so(client: TestClient) -> None:
    review = client.get("/queue/review?q=zzznomatch").text
    assert "No match for zzznomatch." in review
    assert 'data-testid="review-empty"' in review
    assert "No case is in review in this area." not in review
    assert 'data-testid="queue-find-open"' not in review
    work = client.get("/queue?view=all&q=zzznomatch").text
    assert "No match for zzznomatch." in work
    assert 'data-testid="queue-empty"' in work
    assert "Nothing is waiting in this view." not in work
    assert 'data-testid="queue-find-open"' not in work
