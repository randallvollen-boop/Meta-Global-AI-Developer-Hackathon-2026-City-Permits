"""The eight screens of the ACME City interface.

The pages are rendered from the domain services, every write names its
destination and its expected version, and the persona selector offers exactly
the five selectable personas.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04, GOV-04, EDIT-01, EDIT-02, SEC-01, SEC-02
# The pages render the resolved responsibility, keep the value bands apart,
# refuse a write without the CSRF token of the session, and never accept a
# role from the browser.

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
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.ui.router import router as ui_router

#: The eight screens of the demonstration.
SCREENS = (
    "/queue",
    "/applicants",
    "/masters",
    "/steward",
    "/rules-fees",
    "/reconciliation",
    "/governance",
)

#: The fields every governed detail view has to show.
#:
#: Changed deliberately (the City Administrator restyle): the freshness fields
#: are now named "Source last changed" and "Last received or checked", and the
#: issue count is named "Open recorded issues".  Freshness and open issues are
#: two different facts, and the panel says so.
RESPONSIBILITY_FIELDS = (
    "Owner",
    "Steward",
    "Source",
    "Change this in",
    "Source last changed",
    "Last received or checked",
    "Version",
    "Open recorded issues",
)


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'ui-pages.db'}",
            "ACME_SECRET_KEY": "ui-pages-secret-value",
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


def csrf_of(html: str) -> str:
    """Return the CSRF token of a rendered form."""
    match = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    assert match is not None, "the page carries no CSRF token"
    return match.group(1)


def test_the_selector_offers_exactly_the_five_personas(client: TestClient) -> None:
    response = client.get("/select")
    assert response.status_code == 200
    labels = re.findall(r'data-persona="([^"]+)"', response.text)
    assert labels == [
        "persona_applicant",
        "persona_agent_operator",
        "persona_data_steward",
        "persona_permit_reviewer",
        "persona_city_administrator",
    ]
    assert "service_" not in response.text
    assert "Intake Clerk" not in response.text


def test_a_screen_without_a_session_returns_to_the_selector(client: TestClient) -> None:
    response = client.get("/queue", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/select"


def test_the_eight_screens_render_for_the_data_steward(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    for path in ("/queue", "/applicants", "/masters", "/steward", "/rules-fees"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text[:400])
    assert client.get("/reconciliation").status_code == 403
    assert client.get("/governance").status_code == 403


def test_the_eight_screens_render_for_the_city_administrator(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    for path in SCREENS:
        response = client.get(path)
        assert response.status_code == 200, (path, response.text[:400])


def test_the_permit_workspace_is_scoped_to_the_actor(client: TestClient) -> None:
    select_persona(client, "persona_applicant")
    assert client.get("/permits/app_d05").status_code == 200
    assert client.get("/permits/app_synth_001").status_code == 404


def test_the_applicant_may_not_open_the_steward_screen(client: TestClient) -> None:
    select_persona(client, "persona_applicant")
    response = client.get("/steward")
    assert response.status_code == 403
    assert "PER-AP-0003" not in response.text


def test_the_reviewer_may_not_open_the_reconciliation_screen(client: TestClient) -> None:
    select_persona(client, "persona_permit_reviewer")
    response = client.get("/reconciliation")
    assert response.status_code == 403


def test_every_governed_detail_view_shows_the_eight_responsibility_fields(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    # Changed deliberately (steward restyle): the three Data Steward screens
    # keep a short source summary on the page and show the eight responsibility
    # fields in the Source details drawer.  The drawer opens server-rendered
    # with ?detail=source-record:..., so this test reads the page with it open.
    steward_screens = {
        "/applicants/party_cedarline": "permitting:applicant_profiles",
        "/masters/party_cedarline": "erp_finance:business_licensing_register",
        "/steward": "permitting:applicant_profiles",
    }
    for path in (
        "/applicants/party_cedarline",
        "/masters/party_cedarline",
        "/permits/app_synth_001",
        "/steward",
        "/rules-fees",
        "/reconciliation",
        "/governance",
    ):
        address = path
        if path in steward_screens:
            address = f"{path}?detail=source-record:{steward_screens[path]}"
        response = client.get(address)
        assert response.status_code == 200, path
        for field in RESPONSIBILITY_FIELDS:
            assert field in response.text, (path, field)


def test_the_pages_use_no_external_script_or_font(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/queue")
    assert response.status_code == 200
    assert "http://" not in response.text
    assert "https://" not in response.text
    assert "/ui/static/app.css" in response.text
    assert "/ui/static/app.js" in response.text
    assert "Westerville" not in response.text


def test_the_value_bands_are_visibly_distinct(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/permits/app_d07")
    assert response.status_code == 200
    assert "value-current" in response.text
    assert "value-submitted" in response.text
    assert "value-issued" in response.text
    assert "badge-current" in response.text
    assert "badge-submitted" in response.text
    assert "badge-issued" in response.text


def test_a_write_without_the_csrf_token_is_refused_and_changes_nothing(
    client: TestClient,
    environment: tuple[Settings, FixtureBundle],
) -> None:
    settings, _ = environment
    select_persona(client, "persona_permit_reviewer")
    before = client.get("/permits/app_synth_001").text
    response = client.post(
        "/ui/actions/permit.evaluate",
        data={"application_id": "app_synth_001", "next": "/permits/app_synth_001"},
    )
    assert response.status_code == 403
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            evaluations = session.execute(select(permit.Evaluation)).scalars().all()
    finally:
        factory.dispose()
    assert evaluations == []
    assert "Run application checks" in before


def test_a_write_with_a_stale_csrf_token_is_refused(client: TestClient) -> None:
    select_persona(client, "persona_permit_reviewer")
    response = client.post(
        "/ui/actions/permit.evaluate",
        data={
            "application_id": "app_synth_001",
            "csrf_token": "0" * 32,
            "next": "/permits/app_synth_001",
        },
    )
    assert response.status_code == 403


def test_an_action_performs_the_real_transition_and_survives_a_reload(
    client: TestClient,
    environment: tuple[Settings, FixtureBundle],
) -> None:
    settings, _ = environment
    select_persona(client, "persona_permit_reviewer")
    page = client.get("/permits/app_synth_001")
    token = csrf_of(page.text)
    response = client.post(
        "/ui/actions/permit.evaluate",
        data={
            "application_id": "app_synth_001",
            "csrf_token": token,
            "next": "/permits/app_synth_001",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "data-testid=\"feedback\"" in response.text
    assert "Validation finished" in response.text
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            evaluations = session.execute(select(permit.Evaluation)).scalars().all()
    finally:
        factory.dispose()
    assert len(evaluations) == 1
    assert evaluations[0].performed_by_actor_id == "persona_permit_reviewer"

    reloaded = client.get("/permits/app_synth_001")
    assert "Validation finished" in reloaded.text


def test_the_browser_may_not_send_an_authority(client: TestClient) -> None:
    select_persona(client, "persona_applicant")
    page = client.get("/permits/app_d05")
    token = csrf_of(page.text)
    response = client.post(
        "/ui/actions/permit.decide",
        data={
            "application_id": "app_d05",
            "outcome": "approved",
            "reason": "the browser asked for it",
            "role": "permit_reviewer",
            "actor_id": "persona_permit_reviewer",
            "csrf_token": token,
            "next": "/permits/app_d05",
        },
    )
    assert response.status_code == 403
    factory = SessionFactory(client.app.state.settings.database_url)
    try:
        with factory() as session:
            decisions = session.execute(
                select(permit.Decision).where(permit.Decision.application_id == "app_d05")
            ).scalars().all()
    finally:
        factory.dispose()
    assert decisions == []


def test_the_administrator_may_read_a_case_but_not_approve_it(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    page = client.get("/permits/app_synth_001")
    assert page.status_code == 200
    assert 'data-action-id="permit.decide" data-permitted="false"' in page.text
    assert 'data-action-id="permit.issue" data-permitted="false"' in page.text
    assert "your persona does not hold" in page.text


def test_the_persona_switcher_establishes_a_server_held_session(
    client: TestClient,
) -> None:
    response = client.post(
        "/ui/actor",
        data={"actor_id": "persona_permit_reviewer", "next": "/queue"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/queue"
    assert "acme_session" in response.cookies
    session = client.get("/api/session")
    assert session.status_code == 200
    assert session.json()["actor_id"] == "persona_permit_reviewer"


def test_a_service_identity_can_never_hold_a_session(client: TestClient) -> None:
    response = client.post(
        "/ui/actor",
        data={"actor_id": "service_delegate_steward", "next": "/queue"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/select"
    assert client.get("/api/session").status_code == 401
