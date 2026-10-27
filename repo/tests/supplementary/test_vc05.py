"""VC05: the interface reports what actually happened.

After an action the screen shows what changed, the actual destination, the
accepted version or the pending state, and the affected records.  The state
survives a refresh and a navigation, and a success is never shown while a
source or a consumer still has to acknowledge the work.
"""
# REQUIRES: VC05, UX-04, EDIT-04, CHG-02
# The operational feedback names the destination, the accepted version and
# the pending state, survives a refresh and a navigation, and never reports a
# success that the source has not acknowledged.

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import audit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'vc05.db'}",
            "ACME_SECRET_KEY": "vc05-supplementary-secret-value",
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


def csrf_of(body: str) -> str:
    """Return the CSRF token of a rendered form."""
    match = re.search(r'name="csrf_token" value="([0-9a-f]+)"', body)
    assert match is not None
    return match.group(1)


def feedback_of(body: str) -> dict[str, str]:
    """Return the feedback values of a rendered page."""
    values: dict[str, str] = {}
    for name in (
        "feedback-message",
        "feedback-destination",
        "feedback-state",
        "feedback-pending",
        "feedback-version",
        "feedback-affected",
    ):
        match = re.search(
            f'data-testid="{name}"[^>]*>(.*?)</dd>', body, re.S
        ) or re.search(f'data-testid="{name}"[^>]*>(.*?)</p>', body, re.S)
        assert match is not None, name
        values[name] = match.group(1).strip()
    return values


def test_an_action_reports_its_destination_its_state_and_its_version(
    client: TestClient,
) -> None:
    select_persona(client, "persona_permit_reviewer")
    page = client.get("/permits/app_synth_001")
    response = client.post(
        "/ui/actions/permit.evaluate",
        data={
            "application_id": "app_synth_001",
            "csrf_token": csrf_of(page.text),
            "next": "/permits/app_synth_001",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    feedback = feedback_of(response.text)
    assert "Validation finished" in feedback["feedback-message"]
    assert feedback["feedback-destination"] == "Permitting validation"
    assert feedback["feedback-state"]
    assert feedback["feedback-version"] == "1"


def test_the_feedback_survives_a_refresh_and_a_navigation(client: TestClient) -> None:
    select_persona(client, "persona_permit_reviewer")
    page = client.get("/permits/app_synth_001")
    client.post(
        "/ui/actions/permit.evaluate",
        data={
            "application_id": "app_synth_001",
            "csrf_token": csrf_of(page.text),
            "next": "/permits/app_synth_001",
        },
        follow_redirects=True,
    )
    refreshed = client.get("/permits/app_synth_001")
    assert "Validation finished" in feedback_of(refreshed.text)["feedback-message"]
    elsewhere = client.get("/queue")
    assert "Validation finished" in feedback_of(elsewhere.text)["feedback-message"]
    back = client.get("/permits/app_synth_001")
    assert "Validation finished" in feedback_of(back.text)["feedback-message"]


def test_a_proposal_is_reported_as_pending_and_not_as_a_decision(
    client: TestClient,
) -> None:
    select_persona(client, "persona_data_steward")
    page = client.get("/steward")
    response = client.post(
        "/ui/actions/registry.propose",
        data={
            "source_system_id": "permitting",
            "dataset_key": "applicant_profiles",
            "source_record_id": "PER-AP-0003",
            "csrf_token": csrf_of(page.text),
            "next": "/steward",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    feedback = feedback_of(response.text)
    assert "steward decision is still required" in feedback["feedback-message"]
    assert feedback["feedback-pending"].startswith("yes")
    assert "party_cedarline" in feedback["feedback-affected"]


def test_a_refused_action_never_shows_a_success(client: TestClient) -> None:
    select_persona(client, "persona_applicant")
    page = client.get("/permits/app_d05")
    response = client.post(
        "/ui/actions/permit.decide",
        data={
            "application_id": "app_d05",
            "outcome": "approved",
            "reason": "the browser asked for it",
            "csrf_token": csrf_of(page.text),
            "next": "/permits/app_d05",
        },
    )
    assert response.status_code == 403
    assert "data-testid=\"error-panel\"" in response.text
    assert "Validation finished" not in response.text


def test_the_feedback_is_recorded_in_the_append_only_audit_trail(
    client: TestClient,
    environment: tuple[Settings, FixtureBundle],
) -> None:
    settings, _ = environment
    select_persona(client, "persona_permit_reviewer")
    page = client.get("/permits/app_synth_001")
    client.post(
        "/ui/actions/permit.evaluate",
        data={
            "application_id": "app_synth_001",
            "csrf_token": csrf_of(page.text),
            "next": "/permits/app_synth_001",
        },
        follow_redirects=True,
    )
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "ui.permit.evaluate"
                )
            ).scalars().all()
    finally:
        factory.dispose()
    assert len(events) == 1
    event = events[0]
    assert event.actor_id == "persona_permit_reviewer"
    assert event.outcome == "accepted"
    assert event.metadata_json["destination"] == "Permitting validation"
    assert event.metadata_json["state"]
