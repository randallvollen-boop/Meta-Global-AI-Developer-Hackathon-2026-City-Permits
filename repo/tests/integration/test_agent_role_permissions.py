"""The persisted operator entitlement controls all agent-operation grants."""

from __future__ import annotations

from pathlib import Path

import pytest

from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.configuration.service import ConfigurationService
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction


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


def _actor(actor_id: str) -> ActorContext:
    return ActorContext(actor_id=actor_id)


def _can_run(session, actor_id: str) -> bool:
    return PermissionResolver(session).allows(
        _actor(actor_id), "agent.run.intake", ResourceContext(domain_id="permits")
    )


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
