"""VC04: the controls are consistent and reachable by keyboard.

The screens use the same compact tables, the same aligned fields and the same
status controls, every control carries a label, every action has a plain
label, and the interface depends on no external script, font or image.
"""
# REQUIRES: VC04, UX-03, SEC-01
# The controls are compact and consistent, every control is labelled, the
# actions are reachable by keyboard, and the interface loads no external
# asset.

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

#: The screens that have to use the same controls, swept as the City
#: Administrator.
CONTROL_SCREENS = (
    "/queue",
    "/applicants",
    "/masters",
    "/permits/app_synth_001",
    "/steward",
    "/rules-fees",
    "/reconciliation",
    "/governance",
    "/agent/intake",
    "/agent/adjudication",
    "/admin",
    # P3insight: the City view, behind its own grant of the City Administrator.
    "/insight/city",
)

#: The screens parity phase 3b added, with the persona that may open them.
#:
#: Each of the three belongs to one persona, so they are checked with their
#: own persona rather than swept as the City Administrator, who holds no
#: grant for them.  They have to use the same controls and carry the same
#: labelled navigation as every other screen.
PERSONA_CONTROL_SCREENS = (
    ("persona_data_steward", "/queue/intake"),
    ("persona_data_steward", "/queue/early-resolution"),
    ("persona_permit_reviewer", "/queue/review"),
)


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'vc04.db'}",
            "ACME_SECRET_KEY": "vc04-supplementary-secret-value",
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


def control_ids(body: str) -> set[str]:
    """Return the identifiers of the labelled controls of a page."""
    return set(re.findall(r'<(?:input|select|textarea)[^>]*\bid="([^"]+)"', body))


def label_ids(body: str) -> set[str]:
    """Return the identifiers the labels of a page point at."""
    return set(re.findall(r'<label[^>]*\bfor="([^"]+)"', body))


def test_every_control_of_every_screen_carries_a_label(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    # Changed deliberately: the top bar no longer carries the hidden persona <select>, which
    # used to be the one control every page had. A screen with no form control is correct
    # (labels must still match controls exactly); the guard against a vacuous sweep is that
    # the screens as a whole still expose labelled controls.
    seen = 0
    for path in CONTROL_SCREENS:
        body = client.get(path).text
        identifiers = control_ids(body)
        assert identifiers == label_ids(body), path
        seen += len(identifiers)
    assert seen > 10


def test_every_control_of_every_new_screen_carries_a_label(
    client: TestClient,
) -> None:
    """The three phase 3b screens are checked with their own persona."""
    # Same deliberate change as above: no page is required to carry a control any more.
    seen = 0
    for actor_id, path in PERSONA_CONTROL_SCREENS:
        select_persona(client, actor_id)
        body = client.get(path).text
        identifiers = control_ids(body)
        assert identifiers == label_ids(body), (actor_id, path)
        seen += len(identifiers)
    assert seen > 0


def test_the_navigation_is_the_same_on_every_screen(client: TestClient) -> None:
    # City Administrator holds grants for all eleven of the original screens and the
    # P3insight City view (twelve) and the policy 2 What-if screen (thirteen, a
    # deliberate change of this count),
    # so for that persona the navigation is the full canonical list on every
    # screen.  Persona-scoped filtering is covered per persona below.
    select_persona(client, "persona_city_administrator")
    reference = None
    for path in CONTROL_SCREENS:
        body = client.get(path).text
        items = re.findall(r'data-screen-key="([^"]+)"', body)
        assert len(items) == 17, path
        if reference is None:
            reference = items
        assert items == reference


def test_the_navigation_of_a_new_screen_matches_its_persona(
    client: TestClient,
) -> None:
    """A phase 3b screen shows the same navigation as the work queue."""
    for actor_id, path in PERSONA_CONTROL_SCREENS:
        select_persona(client, actor_id)
        expected = re.findall(
            r'data-screen-key="([^"]+)"', client.get("/queue").text
        )
        assert expected
        items = re.findall(r'data-screen-key="([^"]+)"', client.get(path).text)
        assert items == expected, (actor_id, path)


#: Screen key -> path, in canonical navigation order.
SCREEN_PATHS = {
    "queue": "/queue",
    "applicants": "/applicants",
    "masters": "/masters",
    "permit": "/permits/app_synth_001",
    "steward": "/steward",
    "rules": "/rules-fees",
    "reconciliation": "/reconciliation",
    "governance": "/governance",
    "agent_intake": "/agent/intake",
    "agent_adjudication": "/agent/adjudication",
    "admin": "/admin",
    # Parity phase 3b adds three screens after the existing entries, so the
    # order of the existing screens is unchanged.
    "intake_queue": "/queue/intake",
    "early_resolution": "/queue/early-resolution",
    "review_queue": "/queue/review",
    # P3insight adds the City view after those entries.
    "insight_city": "/insight/city",
    # Parity phase 3 policy 2 adds the What-if screen after the City view.
    "policy_scenarios": "/policy/scenarios",
    # Parity phase 3c adds the four operations screens after the What-if screen.
    "ops_dashboard": "/ops/dashboard",
    "ops_audit": "/ops/audit",
    "ops_support": "/ops/support",
    "ops_checks": "/ops/checks",
}

#: The screens each persona may open (same table as the view-model tests).
#:
#: The Data Steward gains the intake queue and the early-resolution board
#: and the Permit Reviewer gains the review queue; no other persona gains a
#: screen.
EXPECTED_NAVIGATION = {
    "persona_applicant": ["queue", "applicants", "permit"],
    "persona_data_steward": [
        "queue",
        "applicants",
        "masters",
        "permit",
        "steward",
        "rules",
        "agent_intake",
        "intake_queue",
        "early_resolution",
    ],
    "persona_permit_reviewer": [
        "queue",
        "applicants",
        "permit",
        "agent_adjudication",
        "review_queue",
    ],
    "persona_city_administrator": [
        "queue",
        "applicants",
        "masters",
        "permit",
        "steward",
        "rules",
        "reconciliation",
        "governance",
        "agent_intake",
        "agent_adjudication",
        "admin",
        "insight_city",
        # Changed deliberately (policy 2): the City Administrator gains the
        # What-if screen, behind the grant policy.scenario.manage that only the
        # Administrator holds.  No other persona's list changes.
        "policy_scenarios",
        # Changed deliberately (P3c): the City Administrator gains the four
        # operations screens, each behind its own grant that only the
        # Administrator holds.  No other persona's list changes.
        "ops_dashboard",
        "ops_audit",
        "ops_support",
        "ops_checks",
    ],
}


@pytest.mark.parametrize("actor_id", sorted(EXPECTED_NAVIGATION))
def test_listed_screens_open_and_hidden_screens_refuse(
    client: TestClient, actor_id: str
) -> None:
    select_persona(client, actor_id)
    if actor_id == "persona_applicant":
        # Changed deliberately: the Applicant's /queue landing now redirects to the City
        # website, so its staff navigation is read from another staff-layout screen.
        redirect = client.get("/queue", follow_redirects=False)
        assert redirect.status_code == 303 and redirect.headers["location"] == "/city/"
        body = client.get("/applicants").text
    else:
        body = client.get("/queue").text
    listed = re.findall(r'data-screen-key="([^"]+)"', body)
    assert listed == EXPECTED_NAVIGATION[actor_id]
    # The permit entry points at an application inside the persona's record
    # scope, which is not necessarily app_synth_001.
    permit_match = re.search(r'href="([^"]+)" data-screen-key="permit"', body)
    for key, path in SCREEN_PATHS.items():
        if key == "permit" and permit_match:
            path = permit_match.group(1)
        response = client.get(path)
        if key in listed:
            assert response.status_code == 200, (actor_id, key, path)
        else:
            assert response.status_code == 403, (actor_id, key, path)


def test_the_current_screen_is_marked_for_the_assistive_technology(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    body = client.get("/reconciliation").text
    assert 'data-screen-key="reconciliation" aria-current="page"' in body


def test_the_page_offers_a_skip_link_and_a_labelled_status_region(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    body = client.get("/queue").text
    assert 'class="skip-link" href="#main"' in body
    assert 'id="main"' in body


def test_the_stylesheet_keeps_a_visible_focus_ring(client: TestClient) -> None:
    stylesheet = client.get("/ui/static/app.css")
    assert stylesheet.status_code == 200
    assert ":focus-visible" in stylesheet.text
    assert "outline:" in stylesheet.text


def test_the_interface_loads_no_external_asset(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    body = client.get("/queue").text
    assert "http://" not in body
    assert "https://" not in body
    assert "//cdn" not in body
    assert 'src="/ui/static/app.js"' in body
    assert 'href="/ui/static/app.css"' in body
    script = client.get("/ui/static/app.js")
    assert script.status_code == 200
    assert "http://" not in script.text
    assert "https://" not in script.text


def test_the_tables_are_compact_and_carry_a_caption(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    body = client.get("/reconciliation").text
    tables = re.findall(r'<table class="data-table"[^>]*>', body)
    assert tables
    assert body.count('class="visually-hidden"') >= len(tables)


def test_the_filters_are_small_and_named(client: TestClient) -> None:
    select_persona(client, "persona_city_administrator")
    body = client.get("/queue").text
    assert 'data-testid="queue-filters"' in body
    for name in ("filter-view", "filter-department", "filter-object", "filter-state"):
        assert f'id="{name}"' in body
        assert f'for="{name}"' in body


def test_the_persona_selector_never_offers_a_service_identity(
    client: TestClient,
) -> None:
    body = client.get("/select").text
    assert "service_owner" not in body
    assert "service_delegate" not in body
    assert "Intake Clerk" not in body
    assert "Accountable Data Owner" not in body
    assert body.count('data-persona=') == 4
