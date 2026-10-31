"""The fictional City of Acme website and the portal inside its layout."""
# REQUIRES: PORTAL-01, UX-01

from __future__ import annotations

import html
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


def test_permits_entry_gives_an_applicant_direct_links(client: TestClient) -> None:
    # Changed deliberately (applicant UI restyle): /city/permits is now the "Permits and applications"
    # page for everyone; an applicant gets plain links, not a redirect past it.
    choose(client, "persona_applicant")
    response = client.get("/city/permits", follow_redirects=False)
    assert response.status_code == 200
    assert 'href="/apply"' in response.text and 'href="/apply/track"' in response.text
    assert 'action="/ui/actor"' not in response.text.split('data-testid="permits-entry"')[1].split("</section>")[0]


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


def test_switcher_lists_exactly_five_personas(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    text = client.get("/queue").text
    assert 'data-testid="demo-switch"' in text
    ids = re.findall(r'data-demo-persona="([^"]+)"', text)
    assert sorted(ids) == sorted(("persona_applicant", *STAFF, "persona_agent_operator"))
    assert "Demo controls" in text


@pytest.mark.parametrize("path", ["/city/", "/apply", "/city/community"])
def test_the_city_site_carries_no_switcher(client: TestClient, path: str) -> None:
    # Changed deliberately (persona switcher, S4): the switcher is a staff
    # control now; the public City website and the permit application carry
    # none.
    choose(client, "persona_applicant")
    text = client.get(path).text
    assert "data-demo-persona" not in text, path
    assert "Demo controls" not in text, path


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
    # Changed deliberately (steward restyle, STW-2): the Data Steward lands on
    # its own work queue when the switch names no destination.
    assert bare.headers["location"] == "/steward"


def test_the_old_in_app_applicant_landing_redirects_to_the_city_site(client: TestClient) -> None:
    choose(client, "persona_applicant")
    queue = client.get("/queue", follow_redirects=False)
    assert queue.status_code == 303 and queue.headers["location"] == "/city/"
    # the portal and its deep links stay
    assert client.get("/apply").status_code == 200
    assert client.get("/apply/track").status_code == 200


def test_the_staff_layout_says_the_switcher_is_for_demonstration_only(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    staff = client.get("/queue").text
    city = client.get("/city/").text
    # Changed deliberately (staff frame, S1 and city frame, S2): neither frame
    # carries a banner any more, so the sentence that explains the switcher
    # lives in the switcher itself.  The long note is cut (demo controls, S3):
    # the control announces itself as a demonstration control and nothing else.
    # The switcher is a staff control (persona switcher, S4), so the City
    # website carries none.
    assert 'data-testid="demo-switch"' in staff
    assert "Demo controls" in staff
    assert "Demonstration control for switching users" not in staff
    assert "role would come from that sign-in" not in staff
    assert "data-demo-persona" not in city
    assert "Fictional ACME City demonstration." in staff
    assert "Fictional City of Acme website" in city


# ------------------------------------------------- persona switch smoothing

def _switch(client: TestClient, actor_id: str, next_path: str):
    return client.post(
        "/ui/actor", data={"actor_id": actor_id, "next": next_path}, follow_redirects=False
    )


def test_switching_from_a_screen_the_new_persona_cannot_open_lands_on_its_home(client: TestClient) -> None:
    choose(client, "persona_city_administrator")
    done = _switch(client, "persona_data_steward", "/admin")
    assert done.status_code == 303
    home, _, query = done.headers["location"].partition("?")
    assert query == "moved_from=admin"
    page = client.get(done.headers["location"])
    assert page.status_code == 200
    assert "Data Steward can't open Administration, so you're on" in html.unescape(page.text)
    assert 'data-testid="moved-notice"' in page.text
    # the home is the first screen of the new persona's own navigation, not a label rule
    nav = re.findall(r'data-screen-key="([a-z_]+)"', page.text)
    assert nav and home == {"queue": "/queue", "applicants": "/applicants"}.get(nav[0], home)

    choose(client, "persona_data_steward")
    done = _switch(client, "persona_permit_reviewer", "/queue/early-resolution")
    assert "moved_from=early_resolution" in done.headers["location"]
    page = client.get(done.headers["location"])
    assert "Permit Reviewer can't open Early resolution" in html.unescape(page.text)

    done = _switch(client, "persona_applicant", "/admin")
    assert done.headers["location"] == "/city/?moved_from=admin"
    assert "Applicant can't open Administration, so you're on the City website instead." in html.unescape(
        client.get(done.headers["location"]).text
    )


def test_a_switch_onto_a_permitted_screen_stays_there(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    assert _switch(client, "persona_permit_reviewer", "/queue").headers["location"] == "/queue"
    assert _switch(client, "persona_city_administrator", "/admin").headers["location"] == "/admin"
    assert _switch(client, "persona_data_steward", "/queue/intake").headers["location"] == "/queue/intake"
    assert "moved-notice" not in client.get("/queue/intake").text


def test_a_refused_screen_keeps_the_navigation_and_offers_home(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    response = client.get("/admin")
    assert response.status_code == 403
    page = response.text
    assert 'data-testid="error-panel"' in page and 'data-testid="go-home"' in page
    assert re.search(r'data-testid="go-home">Go to [^<]+</a>', page)
    keys = re.findall(r'data-screen-key="([a-z_]+)"', page)
    assert keys and "admin" not in keys
    assert 'href="/queue"' in page or 'href="/applicants"' in page
    # the refusal itself leaks nothing from the screen
    assert "Administration</h1>" not in page


def test_the_toast_is_anchored_to_the_top_right() -> None:
    css = (Path(__file__).resolve().parents[2] / "src/acme_city/static")
    app = (css / "app.css").read_text()
    toast = re.search(r"\n\.toast \{([^}]*)\}", app).group(1)
    assert "top:" in toast and "right:" in toast and "bottom:" not in toast
    assert 'toast-top-right' in (css.parent / "templates/base.html").read_text()
    # Changed deliberately (persona switcher, S4): the switcher is the chip in
    # the top bar of the frame, not a floating control in a corner.
    assert 'data-testid="persona-trigger"' in (css.parent / "templates/base.html").read_text()
    assert "demo-corner-bottom-left" not in (css.parent / "templates/base.html").read_text()


def test_the_top_bar_names_the_account_and_signs_out(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    page = client.get("/queue").text
    assert 'class="seg-btn"' not in page and 'class="seg"' not in page
    assert 'data-testid="acting-persona"' in page and "Data Steward" in page
    assert 'action="/ui/end"' in page and 'data-testid="sign-out"' in page
    assert 'id="toast"' in page and 'aria-live="polite"' in re.search(r'<div[^>]*id="toast"[^>]*>', page).group(0)
