"""The navigation plugins, the reserved screens and the More tools group.

A lane changes the navigation only through ``NAV_PROFILES``,
``HOME_OVERRIDES`` and ``register_screen``, from a module that
``nav_plugins.load_plugins`` imports.  With nothing registered the
navigation of every persona is unchanged.  The reserved screens exist in the
tables and a persona reaches one only once its slice has built the route.

The tests compare against what the navigation computes, not against literal
lists, so a lane that registers a profile or grants a reserved permission
does not have to edit this file.  Grant changes of the original personas are
checked by the grant snapshot of W0-3.
"""
# REQUIRES: UX-01, SEC-02
# The navigation lists only the screens a persona holds a grant for, and a
# reserved screen is reachable only once its slice builds the route.

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.ui import nav_plugins, screen_meta, view_models
from acme_city.ui.router import router as ui_router

REPO = Path(__file__).resolve().parents[2]

#: The permission ids W0-2 reserves for the later slices.
RESERVED_PERMISSIONS = (
    "agent.ops.read",
    "permit.intake.queue.view",
    "agent.policy.manage",
    "admin.role.permissions.manage",
    "agent.run.linking",
    "registry.automation.preview",
    "registry.automation.activate",
    "registry.automation.pause",
    "registry.automation.enqueue",
    "registry.automation.review",
    "registry.automation.undo",
    "registry.master.create",
)

#: The reserved screens and their paths.
RESERVED_SCREENS = {
    "agents_home": "/agents",
    "agent_runs": "/agents/runs",
    "steward_automation": "/steward/automation",
}

PERSONAS = (
    "persona_applicant",
    "persona_data_steward",
    "persona_permit_reviewer",
    "persona_city_administrator",
)


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'ui-nav-plugins.db'}",
            "ACME_SECRET_KEY": "ui-nav-plugins-secret-value",
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
def session(environment: Settings) -> Session:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as open_session:
            yield open_session
    finally:
        factory.dispose()


@pytest.fixture()
def client(environment: Settings) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def actor_for(session: Session, actor_id: str) -> ActorContext:
    """Return the acting context of one seeded persona."""
    grants = PermissionResolver(session).grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        role_ids=frozenset(),
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


def select_persona(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def _secondary_last_two(items: list[dict]) -> list[dict]:
    """A dummy profile: the last two entries go under More tools."""
    items = [dict(item) for item in items]
    for item in items[-2:]:
        item["group"] = "secondary"
    return items


# ------------------------------------------------------------- permissions


def test_the_reserved_permissions_are_in_the_catalog() -> None:
    catalog = json.loads((REPO / "config" / "permissions.json").read_text(encoding="utf-8"))
    ids = [entry["permission_id"] for entry in catalog["permissions"]]
    assert len(ids) == len(set(ids))
    for permission in RESERVED_PERMISSIONS:
        assert permission in ids, permission


def test_every_screen_grant_is_in_the_catalog() -> None:
    catalog = json.loads((REPO / "config" / "permissions.json").read_text(encoding="utf-8"))
    ids = {entry["permission_id"] for entry in catalog["permissions"]}
    for key, grants in view_models.SCREEN_PERMISSIONS.items():
        for permission, _domain in grants:
            assert permission in ids, (key, permission)


def _has_route(client: TestClient, href: str) -> bool:
    """Whether the application serves ``href`` or a path below it."""
    def includes(routes) -> bool:
        for route in routes:
            path = getattr(route, "path", "")
            if path == href or path.startswith(href + "/"):
                return True
            nested = getattr(route, "original_router", None)
            if nested is not None and includes(nested.routes):
                return True
        return False

    return includes(client.app.routes)


def test_a_reserved_screen_is_reachable_only_once_its_route_exists(
    session: Session, client: TestClient
) -> None:
    for actor_id in PERSONAS:
        actor = actor_for(session, actor_id)
        keys = {item["key"] for item in view_models.navigation(session, actor)}
        for key, href in RESERVED_SCREENS.items():
            if key in keys or view_models.may_open_screen(session, actor, key):
                assert _has_route(client, href), (actor_id, key)


def _serves_exactly(client: TestClient, href: str) -> bool:
    """Whether the application serves ``href`` itself.

    A route that takes an identifier does not serve the path without one, so
    ``/agents/cases/{application_id}`` does not serve ``/agents/cases``.
    """
    def includes(routes) -> bool:
        for route in routes:
            if getattr(route, "path", "") == href:
                return True
            nested = getattr(route, "original_router", None)
            if nested is not None and includes(nested.routes):
                return True
        return False

    return includes(client.app.routes)


def test_the_navigation_table_holds_no_entry_that_points_nowhere(
    client: TestClient,
) -> None:
    """Every screen of the table is served at its own address."""
    for screen in view_models.SCREENS:
        href = screen["href"]
        if not href:
            # The permit workspace has no address of its own: the navigation
            # points at the case the persona may open.
            continue
        assert _serves_exactly(client, href), (screen["key"], href)


# ----------------------------------------------------------------- screens


def test_the_reserved_screens_are_in_the_tables() -> None:
    keys = [screen["key"] for screen in view_models.SCREENS]
    for key, href in RESERVED_SCREENS.items():
        assert key in keys
        assert view_models.screen_for_path(href) == key
        assert view_models.SCREEN_PERMISSIONS[key]
        assert key in view_models.SCREEN_DOMAIN
        assert key in screen_meta.SCREEN_ICONS
        assert key in screen_meta.SCREEN_SHORT
    assert "Agent Operator" in screen_meta.PERSONA_DOTS


def test_the_longest_href_wins() -> None:
    assert view_models.screen_for_path("/agents/runs") == "agent_runs"
    assert view_models.screen_for_path("/agents/runs/run_1?x=1") == "agent_runs"
    assert view_models.screen_for_path("/agents") == "agents_home"
    assert view_models.screen_for_path("/agent/intake") == "agent_intake"
    assert view_models.screen_for_path("/steward/automation") == "steward_automation"
    assert view_models.screen_for_path("/steward") == "steward"


def test_register_screen_adds_a_screen_and_refuses_a_known_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from acme_city.city import router as city_router

    monkeypatch.setattr(view_models, "SCREEN_PERMISSIONS", dict(view_models.SCREEN_PERMISSIONS))
    monkeypatch.setattr(view_models, "SCREEN_DOMAIN", dict(view_models.SCREEN_DOMAIN))
    saved = list(view_models.SCREENS)
    try:
        view_models.register_screen(
            "probe_screen", "Probe", "/probe", (("agent.ops.read", None),), "permits"
        )
        probe = {"key": "probe_screen", "label": "Probe", "href": "/probe"}
        assert view_models.SCREENS[-1] == probe
        # A module that imported SCREENS by name sees the added screen too.
        assert city_router.SCREENS[-1] == probe
        assert view_models.SCREEN_PERMISSIONS["probe_screen"] == (("agent.ops.read", None),)
        assert view_models.SCREEN_DOMAIN["probe_screen"] == "permits"
        assert view_models.screen_for_path("/probe") == "probe_screen"
        with pytest.raises(ValueError):
            view_models.register_screen("queue", "Again", "/again", (), "permits")
    finally:
        view_models.SCREENS[:] = saved


# ---------------------------------------------------------------- profiles


def test_a_nav_profile_is_applied_and_then_unregistered(session: Session) -> None:
    actor = actor_for(session, "persona_data_steward")
    other = actor_for(session, "persona_permit_reviewer")
    registered = view_models.navigation(session, actor)
    other_before = view_models.navigation(session, other)
    # A profile a lane registered is set aside for the test and put back.
    saved = view_models.NAV_PROFILES.pop(actor.actor_id, None)
    seen: list[list[str]] = []

    def profile(items: list[dict]) -> list[dict]:
        seen.append([item["key"] for item in items])
        return list(reversed(items))

    try:
        before = view_models.navigation(session, actor)
        view_models.NAV_PROFILES[actor.actor_id] = profile
        applied = view_models.navigation(session, actor)
        assert seen == [[item["key"] for item in before]]
        assert applied == list(reversed(before))
        # The home is the first screen of the navigation the profile returns.
        if actor.actor_id not in view_models.HOME_OVERRIDES:
            assert view_models.home_for(session, actor)["key"] == applied[0]["key"]
        # The profile of one persona leaves the navigation of another alone.
        assert view_models.navigation(session, other) == other_before
    finally:
        view_models.NAV_PROFILES.pop(actor.actor_id, None)
        if saved is not None:
            view_models.NAV_PROFILES[actor.actor_id] = saved
    assert view_models.navigation(session, actor) == registered


def test_a_home_override_replaces_the_first_screen(session: Session) -> None:
    actor = actor_for(session, "persona_data_steward")
    registered = view_models.home_for(session, actor)
    saved = view_models.HOME_OVERRIDES.get(actor.actor_id)
    view_models.HOME_OVERRIDES[actor.actor_id] = "/steward"
    try:
        home = view_models.home_for(session, actor)
        assert home == {"label": "Data issues", "href": "/steward", "key": "steward"}
        assert view_models.home_href({"actor_id": actor.actor_id}, []) == "/steward"
        view_models.HOME_OVERRIDES.pop(actor.actor_id)
        # Without an override the home is the first screen of the navigation.
        first = view_models.navigation(session, actor)[0]
        assert view_models.home_for(session, actor)["href"] == first["href"]
    finally:
        view_models.HOME_OVERRIDES.pop(actor.actor_id, None)
        if saved is not None:
            view_models.HOME_OVERRIDES[actor.actor_id] = saved
    assert view_models.home_for(session, actor) == registered
    assert view_models.home_href(None, None) == "/queue"


# ------------------------------------------------------------------ plugins


def test_load_plugins_imports_the_three_lane_modules() -> None:
    loaded = nav_plugins.load_plugins()
    for name in ("acme_city.ui.steward_nav", "acme_city.ui.admin_nav", "acme_city.ui.agent_nav"):
        assert name in loaded
        assert name in sys.modules
        assert callable(sys.modules[name].register)
    # A lane registers only for actors that exist.
    actors = json.loads((REPO / "config" / "actors.json").read_text(encoding="utf-8"))
    actor_ids = {
        actor["actor_id"] for actor in actors["personas"] + actors["service_identities"]
    }
    assert set(view_models.NAV_PROFILES) <= actor_ids
    assert set(view_models.HOME_OVERRIDES) <= actor_ids


def test_load_plugins_skips_only_a_missing_lane_module(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(nav_plugins, "PLUGIN_MODULES", ("acme_city.ui.no_such_lane_nav",))
    assert nav_plugins.load_plugins() == []
    (tmp_path / "nav_probe_broken_lane.py").write_text(
        "import nav_probe_missing_dependency\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(nav_plugins, "PLUGIN_MODULES", ("nav_probe_broken_lane",))
    with pytest.raises(ModuleNotFoundError) as raised:
        nav_plugins.load_plugins()
    assert raised.value.name == "nav_probe_missing_dependency"
    sys.modules.pop("nav_probe_broken_lane", None)


# ------------------------------------------------------------------ render


def _brand_hrefs(html: str) -> list[str]:
    """The brand links and the hidden app-title link of one page."""
    brand = re.search(r'<div class="brand">.*?</div></div>', html, re.S)
    assert brand is not None
    title = re.search(r'<p class="app-title visually-hidden"><a href="([^"]+)"', html)
    assert title is not None
    return [*re.findall(r'href="([^"]+)"', brand.group(0)), title.group(1)]


def test_the_brand_links_to_the_persona_home(client: TestClient, session: Session) -> None:
    homes = {
        actor_id: view_models.home_for(session, actor_for(session, actor_id))["href"]
        for actor_id in PERSONAS
    }
    for actor_id in ("persona_data_steward", "persona_permit_reviewer", "persona_city_administrator"):
        select_persona(client, actor_id)
        response = client.get("/queue")
        assert response.status_code == 200, actor_id
        assert _brand_hrefs(response.text) == [homes[actor_id]] * 3, actor_id
    # A refused screen links the brand to the home of the persona too: the
    # applicant's home is /queue, which sends it on to the City website.
    for actor_id, refused in (
        ("persona_applicant", "/steward"),
        ("persona_city_administrator", "/queue/review"),
    ):
        select_persona(client, actor_id)
        response = client.get(refused)
        assert response.status_code == 403, (actor_id, refused)
        assert _brand_hrefs(response.text) == [homes[actor_id]] * 3, actor_id


def test_a_secondary_item_renders_the_more_tools_group(client: TestClient) -> None:
    # The Permit Reviewer has no navigation profile, so its navigation shows
    # no More tools group.  The Data Steward has one since its lane grouped
    # the secondary tools (STW-2).
    select_persona(client, "persona_permit_reviewer")
    plain = client.get("/queue").text
    assert "More tools" not in plain
    assert 'class="nav-more' not in plain
    select_persona(client, "persona_data_steward")
    saved = view_models.NAV_PROFILES.get("persona_data_steward")
    view_models.NAV_PROFILES["persona_data_steward"] = _secondary_last_two
    try:
        html = client.get("/queue").text
    finally:
        view_models.NAV_PROFILES.pop("persona_data_steward", None)
        if saved is not None:
            view_models.NAV_PROFILES["persona_data_steward"] = saved
    desktop = re.search(r'<details class="nav-more" data-testid="nav-more".*?</details>', html, re.S)
    mobile = re.search(
        r'<details class="nav-more nav-more-mobile" data-testid="nav-more-mobile".*?</details>',
        html,
        re.S,
    )
    assert desktop is not None and mobile is not None
    assert "More tools" in desktop.group(0) and "More tools" in mobile.group(0)
    # The dummy profile moves the last two accessible steward entries under
    # More tools. STW-19 appends its now-routable automation screen.
    for key, href in (("early_resolution", "/queue/early-resolution"), ("steward_automation", "/steward/automation")):
        assert f'data-screen-key="{key}"' in desktop.group(0)
        assert html.count(f'data-screen-key="{key}"') == 1
        assert f'href="{href}"' in mobile.group(0)
    primary = re.search(r'<nav class="nav app-nav".*?<ul>(.*?)</ul>', html, re.S)
    assert primary is not None and 'data-screen-key="queue"' in primary.group(1)
    for key in ("early_resolution", "steward_automation"):
        assert f'data-screen-key="{key}"' not in primary.group(1)
    # The profile the lane registered is back, so the steward keeps its own
    # group, and a persona without a profile still shows none.
    select_persona(client, "persona_permit_reviewer")
    assert client.get("/queue").text.count("More tools") == 0
