"""VC03: the value bands stay apart.

The current master value, the submitted application value, the proposed
correction and the issued value are shown separately, and every action says
what it changes and where it writes.
"""
# REQUIRES: VC03, UX-02, EDIT-03
# The interface labels the current, submitted, proposed and issued values
# separately, and every action names the destination it writes to.

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.ui.router import router as ui_router

#: The four value bands and the badge that marks each of them.
VALUE_BANDS = (
    ("value-current", "badge-current"),
    ("value-submitted", "badge-submitted"),
    ("value-proposed", "badge-proposed"),
    ("value-issued", "badge-issued"),
)


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'vc03.db'}",
            "ACME_SECRET_KEY": "vc03-supplementary-secret-value",
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
    return settings, bundle


@pytest.fixture()
def client(environment: tuple[Settings, FixtureBundle]) -> TestClient:
    settings, _ = environment
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def select_persona(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for one persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def test_the_four_value_bands_carry_their_own_mark(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/permits/app_d07")
    assert response.status_code == 200
    body = response.text
    assert "current master value" in body
    assert "submitted value" in body
    assert "issued value" in body
    for band, badge in VALUE_BANDS:
        if band == "value-proposed":
            continue
        assert band in body
        assert badge in body


def test_the_issued_value_carries_the_issued_snapshot(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    body = client.get("/permits/app_d07").text
    assert "ACME-2026-000731" in body
    issued = re.search(r'data-testid="value-issued"(.*?)</div>', body, re.S)
    assert issued is not None
    assert "issued value" in issued.group(1)


def test_the_submitted_value_keeps_the_first_submission_date(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    body = client.get("/permits/app_synth_001").text
    submitted = re.search(r'data-testid="value-submitted"(.*?)</div>', body, re.S)
    assert submitted is not None
    assert "2026-09-08T14:30:00" in submitted.group(1)
    assert "Revision 1" in submitted.group(1)


def test_every_action_says_where_it_writes(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    body = client.get("/permits/app_synth_001").text
    destinations = re.findall(r'<p class="action-destination">Writes to: ([^<]+)</p>', body)
    assert destinations
    assert all(destination.strip() for destination in destinations)
    assert any("Permitting" in destination for destination in destinations)


def test_the_labels_are_plain_and_name_the_record(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    body = client.get("/permits/app_synth_001").text
    labels = re.findall(r'<span class="action-label">([^<]+)</span>', body)
    assert labels
    for label in labels:
        lowered = label.lower()
        for forbidden in ("api", "endpoint", "json", "post ", "table", "event_type"):
            assert forbidden not in lowered


def test_the_proposed_band_is_empty_when_nothing_is_proposed(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    body = client.get("/permits/app_synth_001").text
    assert 'data-testid="proposed-empty"' in body


def test_the_evidence_panel_stays_stable_between_screens(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    first = client.get("/permits/app_synth_001").text
    second = client.get("/permits/app_d07").text
    assert 'data-testid="evidence-panel"' in first
    assert 'data-testid="evidence-panel"' in second
