"""The Sample data tab: the button that creates the sample cases.

The administration screen offers a button that creates sample cases for the
demonstration.  It is a governed action: it needs the CSRF token of the
session, it is refused without the configuration grant, it never creates more
than one batch of twenty at a time and it is refused altogether in production
mode.  Every click creates new cases, because the nonce of the run is made on
the server.
"""
# REQUIRES: ING-01, ING-02, PER-01, SEC-01
# The sample cases are created through the governed intake path, the caps are
# refused before anything is written, and the action exists in the
# demonstration only.

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.auth.service import SessionService  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402
from acme_city.fixtures.loader import FixtureBundle  # noqa: E402
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo  # noqa: E402
from acme_city.persistence.models import audit, governance, permit  # noqa: E402
from acme_city.persistence.models.governance import DemoEnvironment  # noqa: E402
from acme_city.persistence.session import (  # noqa: E402
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.ui.router import router as ui_router  # noqa: E402

ADMIN = "persona_city_administrator"

#: The action that creates the sample cases.
ACTION_ID = "intake.generate"

#: The prefix every generated portal reference carries.
GENERATED = "PORTAL-2026-GEN"

SECRET = "sample-data-test-secret-value"


def csrf_of(body: str) -> str:
    """Return the CSRF token of the session from a rendered page."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert match is not None, "the page carries a form token"
    return match.group(1)


def choose(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """A demonstration database of its own, so a test leaves no trace."""
    settings = build_environment(tmp_path, synthetic=False, name="sample-data.db")
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def generated_cases(settings: Settings) -> list[str]:
    """Return the references of the sample cases the database holds."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(permit.Application.source_application_number)
            ).scalars().all()
        return [row for row in rows if row and row.startswith(GENERATED)]
    finally:
        factory.dispose()


def without_the_configuration_grant(settings: Settings) -> None:
    """Take the configuration grant away from the administrator.

    The City Administrator is the only persona that may open the
    administration screen, so the state of a persona that may open it and may
    not create sample cases is reached by taking the one grant away.
    """
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            for grant in session.execute(
                select(governance.ActorGrant).where(
                    governance.ActorGrant.actor_id == ADMIN,
                    governance.ActorGrant.permission_id == "config.manage",
                )
            ).scalars().all():
                session.delete(grant)
    finally:
        factory.dispose()


# ------------------------------------------------------------------- the tab


def test_the_administration_screen_offers_the_sample_data_tab(
    client: TestClient,
) -> None:
    """The tab carries a count field and the button that creates the cases."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=sample-data").text
    assert 'data-testid="admin-tab" data-tab="sample-data"' in body
    assert 'data-testid="admin-sample-data-form"' in body
    assert 'data-testid="admin-sample-data-submit"' in body
    assert 'name="count"' in body
    assert 'max="20"' in body
    assert "Create sample data" in body


def test_a_persona_without_the_grant_sees_a_disabled_button_with_the_reason(
    client: TestClient,
) -> None:
    """A persona that may open the screen but not create the cases sees why."""
    settings = client.app.state.settings
    without_the_configuration_grant(settings)
    choose(client, ADMIN)
    body = client.get("/admin?tab=sample-data").text
    assert 'data-testid="admin-sample-data-form"' not in body
    button = re.search(
        r'<button[^>]*data-testid="admin-sample-data-submit"[^>]*>.*?</button>',
        body,
        re.S,
    )
    assert button is not None, "the button is on the screen"
    assert "disabled" in button.group(0)
    reason = re.search(
        r'<span class="hint" id="admin-sample-data-reason"[^>]*>(.*?)</span>',
        body,
        re.S,
    )
    assert reason is not None, "the reason is beside the button"
    assert "config.manage" in reason.group(1)


def test_the_button_is_refused_for_a_persona_without_the_grant(
    client: TestClient,
) -> None:
    """The server refuses the action, not only the button."""
    settings = client.app.state.settings
    without_the_configuration_grant(settings)
    choose(client, ADMIN)
    client.get("/admin?tab=sample-data")
    # The token of the session is on every form of the screen.
    token = csrf_of(client.get("/admin?tab=users").text)
    response = client.post(
        f"/ui/actions/{ACTION_ID}",
        data={
            "csrf_token": token,
            "action_id": ACTION_ID,
            "next": "/admin?tab=sample-data",
            "count": "3",
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["status"] == "denied"


# ----------------------------------------------------------------- the clicks


def test_a_click_creates_the_cases_and_a_second_click_creates_more(
    client: TestClient,
) -> None:
    """Every click creates new cases, because the run is named on the server."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=sample-data").text
    first = client.post(
        f"/ui/actions/{ACTION_ID}",
        data={
            "csrf_token": csrf_of(body),
            "action_id": ACTION_ID,
            "next": "/admin?tab=sample-data",
            "count": "4",
        },
        headers={"Accept": "application/json"},
    )
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["status"] == "accepted", payload
    assert len(payload["affected"]) == 4, payload

    body = client.get("/admin?tab=sample-data").text
    second = client.post(
        f"/ui/actions/{ACTION_ID}",
        data={
            "csrf_token": csrf_of(body),
            "action_id": ACTION_ID,
            "next": "/admin?tab=sample-data",
            "count": "4",
        },
        headers={"Accept": "application/json"},
    )
    assert second.status_code == 200, second.text
    payload = second.json()
    assert payload["status"] == "accepted", payload
    assert len(payload["affected"]) == 4, payload
    # The second run is a different one, so its cases are new.
    assert not set(payload["affected"]) & set(first.json()["affected"])


def test_the_cases_wait_for_the_intake_agent(client: TestClient) -> None:
    """A created case is a case that waits for a person."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=sample-data").text
    created = client.post(
        f"/ui/actions/{ACTION_ID}",
        data={
            "csrf_token": csrf_of(body),
            "action_id": ACTION_ID,
            "next": "/admin?tab=sample-data",
            "count": "2",
        },
        headers={"Accept": "application/json"},
    )
    assert created.status_code == 200, created.text
    settings = client.app.state.settings
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number.in_(
                        created.json()["affected"]
                    )
                )
            ).scalars().all()
            assert len(rows) == 2
            assert {row.status for row in rows} == {"submitted"}
            assert {row.scenario_id for row in rows} == {None}
    finally:
        factory.dispose()


def test_the_click_is_audited(client: TestClient) -> None:
    """The action writes its audit row, with the acting persona."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=sample-data").text
    created = client.post(
        f"/ui/actions/{ACTION_ID}",
        data={
            "csrf_token": csrf_of(body),
            "action_id": ACTION_ID,
            "next": "/admin?tab=sample-data",
            "count": "2",
        },
        headers={"Accept": "application/json"},
    )
    assert created.status_code == 200, created.text
    settings = client.app.state.settings
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "ui.intake.generate"
                )
            ).scalars().all()
            assert len(events) == 1
            assert events[0].actor_id == ADMIN
            assert events[0].outcome == "accepted"
    finally:
        factory.dispose()


def test_a_click_without_a_token_is_refused(client: TestClient) -> None:
    """A form that did not come from this session is refused."""
    choose(client, ADMIN)
    response = client.post(
        f"/ui/actions/{ACTION_ID}",
        data={"action_id": ACTION_ID, "next": "/admin?tab=sample-data", "count": "3"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "permission_denied", response.json()


@pytest.mark.parametrize("count", ["21", "0", "-1"])
def test_a_count_over_the_cap_is_refused_with_a_message(
    client: TestClient, count: str
) -> None:
    """One click creates at most twenty cases."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=sample-data").text
    response = client.post(
        f"/ui/actions/{ACTION_ID}",
        data={
            "csrf_token": csrf_of(body),
            "action_id": ACTION_ID,
            "next": "/admin?tab=sample-data",
            "count": count,
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 422, response.text
    payload = response.json()
    assert payload["status"] == "denied"
    assert "at most 20" in payload["message"], payload


def test_an_unknown_scenario_is_a_refusal_and_not_a_crash(client: TestClient) -> None:
    """The simulator refuses a scenario it does not know."""
    choose(client, ADMIN)
    body = client.get("/admin").text
    response = client.post(
        "/ui/actions/intake.simulate",
        data={
            "csrf_token": csrf_of(body),
            "action_id": "intake.simulate",
            "next": "/admin",
            "scenario": "no-such-scenario",
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 422, response.text
    payload = response.json()
    assert payload["status"] == "denied"
    assert "unknown intake scenario" in payload["message"], payload


# --------------------------------------------------------------- the allowance


def test_the_total_allowance_is_refused(client: TestClient) -> None:
    """The demonstration holds at most two hundred sample cases."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=sample-data").text
    created = client.post(
        f"/ui/actions/{ACTION_ID}",
        data={
            "csrf_token": csrf_of(body),
            "action_id": ACTION_ID,
            "next": "/admin?tab=sample-data",
            "count": "20",
        },
        headers={"Accept": "application/json"},
    )
    assert created.status_code == 200, created.text
    after = client.get("/admin?tab=sample-data").text
    assert "20 sample cases exist now." in after
    assert "At most 20 cases at a time, 200 in all." in after


# ------------------------------------------------------------------ production


@pytest.fixture()
def production_client(tmp_path: Path) -> TestClient:
    """A production deployment with the same records and no demonstration."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'production.db'}",
            "ACME_DEPLOYMENT_MODE": "production",
            "ACME_SECRET_KEY": SECRET,
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
        with transaction(factory) as session:
            # A production database is not marked as the demonstration.
            for marker in session.query(DemoEnvironment).all():
                session.delete(marker)
    finally:
        factory.dispose()
    app = create_app(settings)
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


def test_production_shows_no_sample_data_tab_and_refuses_the_action(
    production_client: TestClient,
) -> None:
    """The action belongs to the demonstration and is gone in production."""
    settings = production_client.app.state.settings
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            cookie = SessionService(session, settings).select_actor(ADMIN)
    finally:
        factory.dispose()
    production_client.cookies.set(cookie.cookie_name, cookie.value)

    body = production_client.get("/admin").text
    assert 'data-tab="sample-data"' not in body
    assert "Sample data" not in body

    refused = production_client.post(
        f"/ui/actions/{ACTION_ID}",
        data={
            "csrf_token": csrf_of(body),
            "action_id": ACTION_ID,
            "next": "/admin",
            "count": "3",
        },
        headers={"Accept": "application/json"},
    )
    assert refused.status_code == 404, refused.text
    assert generated_cases(settings) == []
