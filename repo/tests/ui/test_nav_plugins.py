"""The navigation plugins, the reserved screens and the More tools group.

A lane changes the navigation only through ``NAV_PROFILES``,
``HOME_OVERRIDES`` and ``register_screen``, from a module that
``nav_plugins.load_plugins`` imports.  With nothing registered the
navigation of every persona is unchanged.  The reserved screens exist in the
tables but are gated on permissions no persona holds yet.
"""
# REQUIRES: UX-01, SEC-02
# The navigation lists only the screens a persona holds a grant for, and a
# reserved permission is granted to nobody until its slice builds the route.

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

#: The permission ids W0-2 reserves.  None of them is granted yet.
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
    "agent_case": "/agents/cases",
    "steward_automation": "/steward/automation",
    "steward_new_master": "/steward/new-master",
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


def test_the_reserved_permissions_exist_and_nobody_holds_them() -> None:
    catalog = json.loads((REPO / "config" / "permissions.json").read_text(encoding="utf-8"))
    ids = [entry["permission_id"] for entry in catalog["permissions"]]
    assert len(ids) == len(set(ids))
    actors_text = (REPO / "config" / "actors.json").read_text(encoding="utf-8")
    for permission in RESERVED_PERMISSIONS:
        assert permission in ids, permission
        for role_id, grants in catalog["role_grants"].items():
            assert permission not in grants, (role_id, permission)
        assert f'"{permission}"' not in actors_text, permission


def test_every_screen_grant_is_in_the_catalog() -> None:
    catalog = json.loads((REPO / "config" / "permissions.json").read_text(encoding="utf-8"))
    ids = {entry["permission_id"] for entry in catalog["permissions"]}
    for key, grants in view_models.SCREEN_PERMISSIONS.items():
        for permission, _domain in grants:
            assert permission in ids, (key, permission)


def test_no_persona_holds_a_grant_for_a_reserved_screen(session: Session) -> None:
    for actor_id in PERSONAS:
        actor = actor_for(session, actor_id)
        keys = {item["key"] for item in view_models.navigation(session, actor)}
        assert not keys & set(RESERVED_SCREENS), actor_id
        for key in RESERVED_SCREENS:
            assert not view_models.may_open_screen(session, actor, key), (actor_id, key)


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
    monkeypatch.setattr(view_models, "SCREENS", view_models.SCREENS)
    monkeypatch.setattr(view_models, "SCREEN_PERMISSIONS", dict(view_models.SCREEN_PERMISSIONS))
    monkeypatch.setattr(view_models, "SCREEN_DOMAIN", dict(view_models.SCREEN_DOMAIN))
    view_models.register_screen(
        "probe_screen", "Probe", "/probe", (("agent.ops.read", None),), "permits"
    )
    assert view_models.SCREENS[-1] == {"key": "probe_screen", "label": "Probe", "href": "/probe"}
    assert view_models.SCREEN_PERMISSIONS["probe_screen"] == (("agent.ops.read", None),)
    assert view_models.SCREEN_DOMAIN["probe_screen"] == "permits"
    assert view_models.screen_for_path("/probe") == "probe_screen"
    with pytest.raises(ValueError):
        view_models.register_screen("queue", "Again", "/again", (), "permits")


# ---------------------------------------------------------------- profiles


def test_a_nav_profile_is_applied_and_then_unregistered(session: Session) -> None:
    actor = actor_for(session, "persona_data_steward")
    before = view_models.navigation(session, actor)
    seen: list[list[str]] = []

    def profile(items: list[dict]) -> list[dict]:
        seen.append([item["key"] for item in items])
        return list(reversed(items))

    view_models.NAV_PROFILES[actor.actor_id] = profile
    try:
        applied = view_models.navigation(session, actor)
        assert seen == [[item["key"] for item in before]]
        assert applied == list(reversed(before))
        # The home is the first screen of the navigation the profile returns.
        assert view_models.home_for(session, actor)["key"] == applied[0]["key"]
        other = actor_for(session, "persona_permit_reviewer")
        assert [item["key"] for item in view_models.navigation(session, other)] == [
            "queue", "applicants", "permit", "agent_adjudication", "review_queue",
        ]
    finally:
        view_models.NAV_PROFILES.pop(actor.actor_id)
    assert view_models.navigation(session, actor) == before


def test_a_home_override_replaces_the_first_screen(session: Session) -> None:
    actor = actor_for(session, "persona_data_steward")
    assert view_models.home_for(session, actor)["href"] == "/queue"
    view_models.HOME_OVERRIDES[actor.actor_id] = "/steward"
    try:
        home = view_models.home_for(session, actor)
        assert home == {"label": "Data issues", "href": "/steward", "key": "steward"}
        assert view_models.home_href({"actor_id": actor.actor_id}, []) == "/steward"
    finally:
        view_models.HOME_OVERRIDES.pop(actor.actor_id)
    assert view_models.home_for(session, actor)["href"] == "/queue"
    assert view_models.home_href(None, None) == "/queue"


# ------------------------------------------------------------------ plugins


def test_load_plugins_imports_the_three_lane_modules() -> None:
    loaded = nav_plugins.load_plugins()
    for name in ("acme_city.ui.steward_nav", "acme_city.ui.admin_nav", "acme_city.ui.agent_nav"):
        assert name in loaded
        assert name in sys.modules
        assert callable(sys.modules[name].register)
    assert not view_models.NAV_PROFILES
    assert not view_models.HOME_OVERRIDES


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


def test_the_brand_links_to_the_persona_home(client: TestClient) -> None:
    for actor_id, home in (
        ("persona_data_steward", "/queue"),
        ("persona_permit_reviewer", "/queue"),
        ("persona_city_administrator", "/overview"),
    ):
        select_persona(client, actor_id)
        html = client.get("/queue").text
        brand = re.search(r'<div class="brand">.*?</div></div>', html, re.S)
        assert brand is not None
        assert re.findall(r'href="([^"]+)"', brand.group(0)) == [home, home], actor_id
        title = re.search(r'<p class="app-title visually-hidden"><a href="([^"]+)"', html)
        assert title is not None and title.group(1) == home, actor_id


def test_a_secondary_item_renders_the_more_tools_group(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    plain = client.get("/queue").text
    assert "More tools" not in plain
    assert 'class="nav-more' not in plain
    view_models.NAV_PROFILES["persona_data_steward"] = _secondary_last_two
    try:
        html = client.get("/queue").text
    finally:
        view_models.NAV_PROFILES.pop("persona_data_steward")
    desktop = re.search(r'<details class="nav-more" data-testid="nav-more".*?</details>', html, re.S)
    mobile = re.search(
        r'<details class="nav-more nav-more-mobile" data-testid="nav-more-mobile".*?</details>',
        html,
        re.S,
    )
    assert desktop is not None and mobile is not None
    assert "More tools" in desktop.group(0) and "More tools" in mobile.group(0)
    # The last two entries of the steward are under More tools and nowhere else.
    for key, href in (("intake_queue", "/queue/intake"), ("early_resolution", "/queue/early-resolution")):
        assert f'data-screen-key="{key}"' in desktop.group(0)
        assert html.count(f'data-screen-key="{key}"') == 1
        assert f'href="{href}"' in mobile.group(0)
    primary = re.search(r'<nav class="nav app-nav".*?<ul>(.*?)</ul>', html, re.S)
    assert primary is not None and 'data-screen-key="queue"' in primary.group(1)
    assert 'data-screen-key="intake_queue"' not in primary.group(1)
    assert client.get("/queue").text.count("More tools") == 0
