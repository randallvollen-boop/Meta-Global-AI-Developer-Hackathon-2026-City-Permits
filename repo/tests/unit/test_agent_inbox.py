"""The Incoming list on the Agents screen: generated and seeded cases waiting for the agent."""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.portal_intake.service import IntakeService
from acme_city.ui.router import router as ui_router


class _Forms(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.forms.append({"action": a.get("action"), "fields": {}, "buttons": []})
        elif self.forms and tag == "input" and a.get("type") == "hidden":
            self.forms[-1]["fields"][a["name"]] = a.get("value", "")
        elif self.forms and tag == "button":
            self.forms[-1]["buttons"].append(a)


def _inbox_forms(client: TestClient) -> list[dict]:
    parser = _Forms()
    parser.feed(client.get("/agents").text)
    return [
        f for f in parser.forms
        if any(b.get("data-testid") == "agent-inbox-process" for b in f["buttons"])
    ]


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'inbox.db'}",
            "ACME_SECRET_KEY": "agent-inbox-test-secret",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(DemoEnvironment(
                id="demo_environment_local", environment_id=ENVIRONMENT_ID,
                fictional_demo=True, fixture_version=bundle.fixture_version,
                label="local fictional demonstration",
            ))
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
        with transaction(factory) as session:
            grants = PermissionResolver(session).grants_for("persona_city_administrator")
            admin = ActorContext(
                actor_id="persona_city_administrator",
                role_ids=frozenset(
                    r[0] for r in session.execute(
                        select(ActorRole.role_id).where(
                            ActorRole.actor_id == "persona_city_administrator"
                        )
                    ).all()
                ),
                domain_scope=frozenset(g.domain_id for g in grants if g.domain_id),
                record_scope=frozenset(r for g in grants for r in g.record_scope),
            )
            IntakeService(
                session, settings=settings, document_root=tmp_path / "documents"
            ).generate_cases(seed=7, count=6, nonce="inbox", actor=admin)
    finally:
        factory.dispose()
    return settings


@pytest.fixture()
def client(settings: Settings):
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        assert test_client.post(
            "/api/session/select", json={"actor_id": "persona_agent_operator"}
        ).status_code == 200
        yield test_client


def test_the_generated_cases_appear_in_the_incoming_list(client: TestClient) -> None:
    page = client.get("/agents").text
    assert 'data-testid="agent-inbox"' in page
    assert page.count('data-testid="agent-inbox-row"') == 6
    assert 'data-testid="agent-inbox-case-link"' in page


def test_an_asleep_agent_shows_the_reason_beside_disabled_buttons(client: TestClient) -> None:
    page = client.get("/agents").text
    assert 'data-testid="agent-inbox-sleep"' in page
    assert "The agent is asleep, so the run buttons are off." in page
    assert page.count('aria-describedby="agent-inbox-sleep"') == 6


def test_process_one_click_runs_the_agent_on_that_case(client: TestClient) -> None:
    form = client.get("/agent/intake")
    assert form.status_code == 200
    # Wake the agent the way its screen does.
    parser = _Forms()
    parser.feed(form.text)
    toggle = next(
        f for f in parser.forms
        if any(b.get("data-testid") == "agent-toggle" for b in f["buttons"])
    )
    assert client.post(
        toggle["action"], data=toggle["fields"],
        headers={"Accept": "application/json"}, follow_redirects=False,
    ).json()["status"] == "accepted"

    forms = _inbox_forms(client)
    assert len(forms) == 6
    assert all("disabled" not in f["buttons"][0] for f in forms)
    application_id = forms[0]["fields"]["application_id"]
    response = client.post(
        forms[0]["action"], data=forms[0]["fields"],
        headers={"Accept": "application/json"}, follow_redirects=False,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"
    after = client.get("/agents").text
    assert after.count('data-testid="agent-inbox-row"') == 5
    assert f'data-application-id="{application_id}"' not in after.split('data-testid="agent-inbox"', 1)[1]
