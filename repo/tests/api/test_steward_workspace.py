"""The workspace of the Data Steward over GET requests.

The queue reads its search, its filters and its page from the address of the
request, so a steward can bookmark a queue, send it to a colleague and come
back to it from a case with the same search, the same filters and the same
page.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02, MDM-02, SEC-01

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_demo import CEDARLINE_RECORDS, seed_cedarline
from acme_city.persistence.models import change
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.ui import steward_queue_views as queue
from acme_city.ui.router import router as ui_router

#: The actor id of the Data Steward.
STEWARD = "persona_data_steward"


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    """Return a settings object with its own database under the test folder."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'steward-workspace.db'}",
            "ACME_SECRET_KEY": "steward-workspace-secret-value",
        },
        key_file=tmp_path / "missing.env",
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
    return settings


@pytest.fixture()
def client(environment: Settings) -> TestClient:
    """Return a client that acts as the Data Steward, with work to do."""
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            seed_cedarline(session)
    finally:
        factory.dispose()
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        response = test_client.post("/api/session/select", json={"actor_id": STEWARD})
        assert response.status_code == 200
        yield test_client


def rows_of(html: str) -> list[str]:
    """Return the row selectors of one rendered queue."""
    return re.findall(r'data-issue-row data-testid="([^"]+)"', html)


def test_the_queue_reads_its_search_from_the_address(client: TestClient) -> None:
    """The search narrows the queue to the tasks that match the text."""
    body = client.get("/steward?q=cedarline").text
    assert rows_of(body)
    assert "Cedarline" in body
    empty = client.get("/steward?q=notarecord").text
    assert rows_of(empty) == []
    assert 'data-testid="queue-empty"' in empty


def test_the_search_finds_a_source_reference(client: TestClient) -> None:
    """A steward can search for the reference of the source record."""
    body = client.get("/steward?q=ERP-BL-00413").text
    assert rows_of(body)
    assert "ERP-BL-00413" in body


def test_the_record_type_filter_narrows_the_queue(client: TestClient) -> None:
    """The record type filter keeps the tasks of one kind of work."""
    body = client.get("/steward?record_type=match").text
    assert rows_of(body)
    assert set(rows_of(body)) <= {"match-proposal", "crosswalk-row"}
    other = client.get("/steward?record_type=property").text
    assert rows_of(other) == []


def test_the_source_filter_narrows_the_queue(client: TestClient) -> None:
    """The source filter keeps the tasks of one source."""
    body = client.get("/steward?source=ERP/Finance: Business licences").text
    assert rows_of(body)
    assert all(
        "ERP/Finance" in line
        for line in re.findall(r"<td>([^<]*ERP/Finance[^<]*)</td>", body)
    )


def test_the_views_keep_the_search_and_the_filters(client: TestClient) -> None:
    """Switching a view keeps the search and the filters of the steward."""
    body = client.get("/steward?q=cedarline&record_type=match").text
    links = re.findall(r'href="(/steward\?[^"]+)" data-testid="issue-filter"', body)
    assert links
    for link in links:
        assert "q=cedarline" in link
        assert "record_type=match" in link


def test_the_queue_reports_how_much_work_matches(client: TestClient) -> None:
    """The queue says how many tasks match the search."""
    body = client.get("/steward?q=cedarline").text
    summary = re.search(r'data-testid="queue-summary">([^<]+)<', body)
    assert summary is not None
    assert "tasks match" in summary.group(1)


def test_the_counts_use_the_same_scope_as_the_rows(client: TestClient) -> None:
    """The count behind a view is the number of tasks of that view."""
    body = client.get("/steward").text
    counts = {
        key: int(count)
        for key, count in re.findall(
            r'data-filter="([a-z_]+)"[^>]*>\s*[A-Za-z ]+<span class="n" '
            r'data-testid="issue-filter-count">(\d+)</span>',
            body,
        )
    }
    assert counts["needs_review"] == len(rows_of(body))


def test_a_case_returns_to_the_queue_it_was_opened_from(client: TestClient) -> None:
    """The case keeps the search, the filters and the page of the queue."""
    body = client.get("/steward?q=cedarline").text
    link = re.search(r'href="(/steward/issues/link/[^"]+)"', body)
    assert link is not None
    assert "back=" in link.group(1)
    case = client.get(link.group(1).replace("&amp;", "&"))
    assert case.status_code == 200
    crumb = re.search(r'<p class="crumb"><a href="([^"]+)"', case.text)
    assert crumb is not None
    assert crumb.group(1).endswith("q=cedarline")


def test_a_case_opened_without_a_queue_returns_to_the_queue(client: TestClient) -> None:
    """A case opened on its own still offers the way back to the queue."""
    body = client.get("/steward").text
    link = re.search(r'href="(/steward/issues/link/[^"]+)"', body)
    assert link is not None
    direct_path = link.group(1).replace("&amp;", "&").split("?", maxsplit=1)[0]
    assert "back=" not in direct_path
    case = client.get(direct_path)
    crumb = re.search(r'<p class="crumb"><a href="([^"]+)"', case.text)
    assert crumb is not None
    assert crumb.group(1) == "/steward"


def test_the_queue_pages_the_work(client: TestClient) -> None:
    """The queue shows one page of work and links to the next one."""
    factory = SessionFactory(client.app.state.settings.database_url)
    try:
        with transaction(factory) as session:
            for index in range(queue.PAGE_SIZE + 3):
                session.add(
                    change.ChangeCase(
                        id=f"case_paged_{index:03d}",
                        target_type="party",
                        target_id="party_cedarline",
                        change_kind="factual",
                        correlation_id=f"corr_paged_{index:03d}",
                        title=f"Correct the Cedarline name {index}",
                        status="in_review",
                    )
                )
    finally:
        factory.dispose()
    first = client.get("/steward").text
    assert len(rows_of(first)) == queue.PAGE_SIZE
    assert 'data-testid="pager"' in first
    second = client.get("/steward?page=2").text
    # The second page holds the three seeded proposals and the three tasks
    # the test added.
    assert len(rows_of(second)) == len(CEDARLINE_RECORDS) + 3
    # The page link keeps the search and the filters.
    pager = re.search(r'data-testid="pager".*?</nav>', first, re.S)
    assert pager is not None
    assert "page=2" in pager.group(0)


def test_the_filters_are_read_through_a_get_request(client: TestClient) -> None:
    """The filter form sends its values in the address, never in the body."""
    body = client.get("/steward").text
    form = re.search(r'<form class="queue-filter-form[^"]*".*?</form>', body, re.S)
    assert form is not None
    assert 'method="get"' in form.group(0)
    assert 'name="record_type"' in form.group(0)
    assert 'name="source"' in form.group(0)
