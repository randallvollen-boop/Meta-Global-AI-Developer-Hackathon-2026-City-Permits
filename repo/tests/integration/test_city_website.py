"""The fictional City of Acme website and the portal inside its layout."""
# REQUIRES: PORTAL-01, UX-01

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.applicant_portal import forms
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import audit, gis, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def environment(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("acme_city.applicant_portal.service.DOCUMENT_ROOT", tmp_path / "documents")
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'city.db'}",
            "ACME_SECRET_KEY": "city-test-secret-value",
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
def client(environment) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client



STAFF = ("persona_data_steward", "persona_permit_reviewer", "persona_city_administrator")
STAFF_MARKERS = ('class="side"', "app-nav", 'data-testid="persona-select"', "Permit workspace", "mobile-nav", 'href="/queue"')


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("path", ["/city/", "/city/trash-recycling", "/city/parks", "/city/pay-a-bill", "/city/contact"])
def test_city_pages_render_without_staff_chrome(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert 'data-testid="nav-permits"' in response.text
    assert "<main" in response.text and "skip-link" in response.text
    for marker in STAFF_MARKERS:
        assert marker not in response.text, marker


def test_unknown_city_page_is_404(client: TestClient) -> None:
    assert client.get("/city/nothing-here").status_code == 404


def test_permits_entry_posts_to_existing_selector(client: TestClient) -> None:
    page = client.get("/city/permits")
    assert page.status_code == 200
    assert 'action="/ui/actor"' in page.text
    assert 'name="actor_id" value="persona_applicant"' in page.text
    assert 'name="next" value="/apply"' in page.text
    assert client.get("/apply", follow_redirects=False).status_code == 303
    done = client.post(
        "/ui/actor",
        data={"actor_id": "persona_applicant", "next": "/apply"},
        follow_redirects=False,
    )
    assert done.status_code == 303 and done.headers["location"] == "/apply"
    assert client.get("/apply").status_code == 200


def test_permits_entry_skips_interstitial_for_applicant(client: TestClient) -> None:
    choose(client, "persona_applicant")
    response = client.get("/city/permits", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/apply"


def test_portal_pages_use_city_layout_without_staff_nav(client: TestClient) -> None:
    choose(client, "persona_applicant")
    for path in ("/apply", "/apply/track", "/apply/deck_fence"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert 'data-city-site="true"' in response.text
        assert 'data-testid="city-breadcrumb"' in response.text
        assert 'aria-current="page"' in response.text
        for marker in STAFF_MARKERS:
            assert marker not in response.text, (path, marker)
    assert 'data-testid="application-form"' in client.get("/apply/deck_fence").text
    assert 'name="csrf_token"' in client.get("/apply/deck_fence").text


@pytest.mark.parametrize("path", ["/city/", "/apply", "/queue"])
def test_switcher_lists_exactly_four_personas(client: TestClient, path: str) -> None:
    choose(client, "persona_applicant" if path == "/apply" else "persona_data_steward")
    text = client.get(path).text
    assert 'data-testid="demo-switch"' in text
    ids = re.findall(r'data-demo-persona="([^"]+)"', text)
    assert sorted(ids) == sorted(("persona_applicant", *STAFF))
    assert "Demo: switch user" in text


def test_staff_pages_still_render_and_portal_stays_blocked(client: TestClient) -> None:
    choose(client, "persona_permit_reviewer")
    queue = client.get("/queue")
    assert queue.status_code == 200
    assert 'class="side"' in queue.text and "city-site" not in queue.text
    assert client.get("/apply").status_code == 403


def test_switching_to_applicant_from_a_staff_page_lands_on_the_city_site(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    page = client.get("/queue").text
    assert 'name="next" value="/queue"' in page
    done = client.post(
        "/ui/actor",
        data={"actor_id": "persona_applicant", "next": "/queue"},
        follow_redirects=False,
    )
    assert done.status_code == 303 and done.headers["location"] == "/city/"
    # a bare switch (no next) also lands there
    bare = client.post("/ui/actor", data={"actor_id": "persona_applicant"}, follow_redirects=False)
    assert bare.headers["location"] == "/city/"


def test_staff_persona_switch_keeps_its_destination(client: TestClient) -> None:
    done = client.post(
        "/ui/actor",
        data={"actor_id": "persona_data_steward", "next": "/queue/intake"},
        follow_redirects=False,
    )
    assert done.headers["location"] == "/queue/intake"
    bare = client.post("/ui/actor", data={"actor_id": "persona_data_steward"}, follow_redirects=False)
    assert bare.headers["location"] == "/queue"


def test_the_old_in_app_applicant_landing_redirects_to_the_city_site(client: TestClient) -> None:
    choose(client, "persona_applicant")
    queue = client.get("/queue", follow_redirects=False)
    assert queue.status_code == 303 and queue.headers["location"] == "/city/"
    # the portal and its deep links stay
    assert client.get("/apply").status_code == 200
    assert client.get("/apply/track").status_code == 200


def test_both_layouts_say_the_switcher_is_for_demonstration_only(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    staff = client.get("/queue").text
    city = client.get("/city/").text
    for page in (staff, city):
        assert "ease of" in page and "sign in" in page and "front door" in page
        assert "role would come from that sign-in" in page
    assert "Fictional ACME City demonstration." in staff
    assert "Fictional City of Acme website" in city
