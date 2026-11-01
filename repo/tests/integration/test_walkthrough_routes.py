"""The routes of the walkthrough: the paths, the tour and the fresh copy.

The walkthrough page lists the paths, the tour is served one path at a time
and Start fresh makes a copy of the café case for the visitor.  The copy is
a write, so it needs the token of the visitor, it is capped and it is
audited.
"""
# REQUIRES: UX-04, SEC-02
# The walkthrough reads; Start fresh writes, and the server decides.

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import build_settings, choose  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402
from acme_city.persistence.models import audit, finance, permit  # noqa: E402
from acme_city.persistence.session import SessionFactory, transaction  # noqa: E402
from acme_city.ui.guide_views import PATHS  # noqa: E402


@pytest.fixture()
def demo(tmp_path: Path) -> tuple[TestClient, Settings]:
    """A demonstration server with its own database."""
    settings = build_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, settings


@pytest.fixture()
def client(demo: tuple[TestClient, Settings]) -> TestClient:
    return demo[0]


def judge_token_of(body: str) -> str:
    """Return the token of the visitor that the page carries."""
    match = re.search(r'name="csrf_token" value="([^"]*)"', body)
    assert match is not None, "the page carries no form token"
    return match.group(1)


def test_the_walkthrough_page_lists_every_path(client: TestClient) -> None:
    response = client.get("/walkthrough")
    assert response.status_code == 200
    body = response.text
    for path in PATHS:
        assert f'data-path="{path.key}"' in body
        assert path.title in body
        assert path.one_line in body
        assert f"{path.minutes} minutes" in body
    assert body.count('data-testid="path-start"') == len(PATHS)
    assert body.count('data-testid="path-steps-link"') == len(PATHS)


def test_the_landing_lists_every_path_under_the_personas(client: TestClient) -> None:
    response = client.get("/select")
    assert response.status_code == 200
    body = response.text
    personas = body.index('data-testid="persona-list"')
    paths = body.index('data-testid="landing-paths"')
    assert paths > personas, "the paths stand under the personas"
    for path in PATHS:
        assert f'data-path="{path.key}"' in body
        assert path.one_line in body
    assert body.count('data-testid="landing-path-start"') == len(PATHS)
    assert body.count('data-testid="landing-path-steps"') == len(PATHS)


def test_the_tour_is_served_one_path_at_a_time(client: TestClient) -> None:
    for path in PATHS:
        response = client.get(f"/tour/steps?path={path.key}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["path"] == path.key
        assert payload["steps"], path.key
        for step in payload["steps"]:
            assert step["path"].startswith("/")
            assert step["target"]


def test_the_tour_of_the_café_path_opens_the_case_of_the_café(client: TestClient) -> None:
    payload = client.get("/tour/steps?path=cafe").json()
    screens = [step["path"] for step in payload["steps"]]
    assert "/permits/app_synth_001" in screens


def test_start_fresh_makes_a_copy_and_remembers_it(client: TestClient) -> None:
    body = client.get("/walkthrough").text
    token = judge_token_of(body)

    response = client.post(
        "/walkthrough/start-fresh",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:300]
    assert response.headers["location"].startswith("/walkthrough?case=app_judge_")
    assert client.cookies.get("acme_judge_case")

    body = client.get("/walkthrough").text
    assert 'data-testid="judge-copy-notice"' in body
    assert "CAFE-2026-" in body


def test_start_fresh_refuses_a_write_without_the_token(client: TestClient) -> None:
    response = client.post(
        "/walkthrough/start-fresh",
        data={"csrf_token": ""},
        follow_redirects=False,
    )
    assert response.status_code == 403, response.text[:300]
    assert "CAFE-2026-" not in client.get("/walkthrough").text


def test_start_fresh_refuses_a_write_with_a_wrong_token(client: TestClient) -> None:
    response = client.post(
        "/walkthrough/start-fresh",
        data={"csrf_token": "0" * 32},
        follow_redirects=False,
    )
    assert response.status_code == 403, response.text[:300]


def test_start_fresh_answers_the_browser_of_the_tour(client: TestClient) -> None:
    body = client.get("/walkthrough").text
    token = judge_token_of(body)
    response = client.post(
        "/walkthrough/start-fresh?format=json",
        data={"csrf_token": token},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["reference"].startswith("CAFE-2026-")


def test_start_fresh_accepts_the_token_of_a_signed_in_persona(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    body = client.get("/walkthrough").text
    token = judge_token_of(body)
    response = client.post(
        "/walkthrough/start-fresh",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:300]


def test_start_fresh_lives_in_the_demonstration_only() -> None:
    """The route is mounted by the demonstration router, and by nothing else."""
    from acme_city.ui import guide_routes, walkthrough_routes

    written = {route.path for route in walkthrough_routes.router.routes}
    assert "/walkthrough/start-fresh" in written
    read = {route.path for route in guide_routes.router.routes}
    assert "/tour/steps" in read
    assert "/walkthrough" in read


def test_the_start_fresh_button_is_off_when_the_allowance_is_gone(
    demo: tuple[TestClient, Settings]
) -> None:
    """A disabled button says why, and the reason stands beside it."""
    from acme_city.walkthrough.judge_copy import MAX_JUDGE_COPIES, create_judge_copy

    client, settings = demo
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            for index in range(MAX_JUDGE_COPIES):
                create_judge_copy(session, nonce=f"FULL{index:04d}")
    finally:
        factory.dispose()

    body = client.get("/walkthrough").text
    assert 'data-testid="path-fresh" disabled' in body
    assert 'aria-describedby="path-fresh-note"' in body
    assert 'data-testid="path-fresh-note"' in body
    assert "allowance" in body

    landing = client.get("/select").text
    assert 'data-testid="landing-path-fresh" disabled' in landing
    assert 'data-testid="landing-path-fresh-note"' in landing


def test_the_copy_of_the_café_is_written_to_the_database(demo: tuple[TestClient, Settings]) -> None:
    """The copy is a real case with a real receipt and one audit event."""
    client, settings = demo
    body = client.get("/walkthrough").text
    token = judge_token_of(body)
    client.post("/walkthrough/start-fresh", data={"csrf_token": token}, follow_redirects=False)

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            copies = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number.like("CAFE-2026-%")
                )
            ).scalars().all()
            assert len(copies) == 1
            receipt = session.execute(
                select(finance.Payment).where(
                    finance.Payment.source_transaction_id.like("ERP-TXN-J%")
                )
            ).scalars().one()
            assert receipt.amount_cents == 15000
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "walkthrough.start_fresh"
                )
            ).scalars().all()
            assert len(events) == 1
    finally:
        factory.dispose()
