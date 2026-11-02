"""Recovery when a visitor's café copy disappeared after a data reset."""
# REQUIRES: UX-04

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import build_settings, choose  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402
from acme_city.persistence.session import SessionFactory, transaction  # noqa: E402
from acme_city.walkthrough.judge_copy import (  # noqa: E402
    COPIES_IN_USE,
    MAX_JUDGE_COPIES,
    create_judge_copy,
)


MISSING_CASE_ID = "app_judge_79750d"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    settings: Settings = build_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def test_a_missing_tour_case_has_a_recovery_page(client: TestClient) -> None:
    """A reset copy keeps the app frame and lets the visitor start over."""
    choose(client, "persona_permit_reviewer")
    client.cookies.set("acme_judge_case", MISSING_CASE_ID)

    response = client.get(f"/permits/{MISSING_CASE_ID}")

    assert response.status_code == 404
    assert 'data-case-missing="true"' in response.text
    assert re.search(r"<h1[^>]*>This case is no longer here</h1>", response.text)
    assert (
        "The demonstration data was reset, so this copy of the case is gone."
        in response.text
    )
    assert 'action="/walkthrough/start-fresh"' in response.text
    assert ">Start fresh</button>" in response.text
    assert 'href="/walkthrough"' in response.text
    assert MISSING_CASE_ID not in response.text
    assert "acme_judge_case" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_a_missing_tour_case_keeps_the_existing_copy_limit(client: TestClient) -> None:
    """Start fresh explains the ordinary allowance limit on the recovery page."""
    settings: Settings = client.app.state.settings
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            for index in range(MAX_JUDGE_COPIES):
                create_judge_copy(session, nonce=f"MISS{index:04d}")
    finally:
        factory.dispose()
    choose(client, "persona_permit_reviewer")

    response = client.get(f"/permits/{MISSING_CASE_ID}")

    assert response.status_code == 404
    assert 'data-testid="missing-case-start-fresh" disabled' in response.text
    assert COPIES_IN_USE in response.text
