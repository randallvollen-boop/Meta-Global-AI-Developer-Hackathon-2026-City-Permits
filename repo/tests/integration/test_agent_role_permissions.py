"""The persisted operator entitlement controls all agent-operation grants."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.configuration.service import ConfigurationService
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

#: The personas that are not the City Administrator, and a screen each of them
#: may open to read a valid token from.
NON_ADMIN_PATHS: dict[str, str] = {
    "persona_data_steward": "/queue/intake",
    "persona_permit_reviewer": "/queue/intake",
    "persona_agent_operator": "/agent/intake",
}


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'role-permissions.db'}",
            "ACME_SECRET_KEY": "role-permissions-test-secret",
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
    finally:
        factory.dispose()
    return settings


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def _actor(actor_id: str) -> ActorContext:
    return ActorContext(actor_id=actor_id)


def _can_run(session, actor_id: str) -> bool:
    return PermissionResolver(session).allows(
        _actor(actor_id), "agent.run.intake", ResourceContext(domain_id="permits")
    )


def _choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def _csrf(client: TestClient, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def _set_city_worker(settings: Settings, enabled: bool) -> None:
    """Turn the City worker option on or off, as the City Administrator."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            service = ConfigurationService(session)
            admin = _actor("persona_city_administrator")
            for role_id in ("permit_reviewer", "intake_clerk"):
                service.set_agent_role_entitlement(
                    role_id=role_id,
                    can_run_agents=enabled,
                    reason="Winter coverage" if enabled else "Winter coverage ended",
                    actor=admin,
                )
    finally:
        factory.dispose()


def test_reset_leaves_only_the_operator_with_agent_operation_grants(settings: Settings) -> None:
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            assert _can_run(session, "persona_agent_operator")
            for actor_id in (
                "persona_data_steward",
                "persona_permit_reviewer",
                "persona_city_administrator",
            ):
                assert not _can_run(session, actor_id)
    finally:
        factory.dispose()


def test_city_worker_option_grants_and_revokes_existing_worker_access(settings: Settings) -> None:
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            service = ConfigurationService(session)
            admin = _actor("persona_city_administrator")
            service.set_agent_role_entitlement(
                role_id="permit_reviewer", can_run_agents=True, reason="Coverage", actor=admin
            )
            service.set_agent_role_entitlement(
                role_id="intake_clerk", can_run_agents=True, reason="Coverage", actor=admin
            )
        with factory() as session:
            assert _can_run(session, "persona_permit_reviewer")
            assert _can_run(session, "persona_data_steward")
        with transaction(factory) as session:
            service = ConfigurationService(session)
            admin = _actor("persona_city_administrator")
            service.set_agent_role_entitlement(
                role_id="permit_reviewer", can_run_agents=False, reason="Coverage ended", actor=admin
            )
            service.set_agent_role_entitlement(
                role_id="intake_clerk", can_run_agents=False, reason="Coverage ended", actor=admin
            )
        with factory() as session:
            assert not _can_run(session, "persona_permit_reviewer")
            assert not _can_run(session, "persona_data_steward")
    finally:
        factory.dispose()


def test_non_admin_cannot_change_the_role_entitlement(settings: Settings) -> None:
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            with pytest.raises(PermissionDeniedError):
                ConfigurationService(session).set_agent_role_entitlement(
                    role_id="permit_reviewer", can_run_agents=True, reason="No authority",
                    actor=_actor("persona_permit_reviewer"),
                )
    finally:
        factory.dispose()


@pytest.mark.parametrize("actor_id", sorted(NON_ADMIN_PATHS))
def test_a_non_administrator_cannot_save_the_role_permissions(
    client: TestClient, actor_id: str
) -> None:
    """The saving action of the Users tab is the administrator's own."""
    _choose(client, actor_id)
    path = NON_ADMIN_PATHS[actor_id]
    response = client.post(
        "/ui/actions/admin.role.permissions",
        data={
            "csrf_token": _csrf(client, path),
            "action_id": "admin.role.permissions",
            "next": path,
            "city_worker_enabled": "true",
            "reason": "No authority",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 403, (actor_id, response.text)


def test_the_reviewer_runs_only_while_city_worker_is_on(
    client: TestClient, settings: Settings
) -> None:
    """The reviewer may run the agents exactly while the City worker option is on."""
    _choose(client, "persona_permit_reviewer")
    path = "/agent/intake"
    assert client.get(path).status_code == 403

    _set_city_worker(settings, True)
    screen = client.get(path)
    assert screen.status_code == 200
    assert 'data-testid="agent-run-all"' in screen.text
    # The run is authorized, so the request reaches the service.  The agent
    # sleeps in the demonstration, so the service refuses the run itself.
    run = client.post(
        "/ui/actions/agent.run.intake",
        data={
            "csrf_token": _csrf(client, path),
            "action_id": "agent.run.intake",
            "next": path,
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert run.status_code == 422, run.text

    _set_city_worker(settings, False)
    assert client.get(path).status_code == 403

