"""Authorization tests: grants, domain scope, record scope and denials."""

from __future__ import annotations

from pathlib import Path

import pytest

from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import Actor, ActorRole, DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'authorization.db'}",
            "ACME_SECRET_KEY": "authorization-test-secret-value",
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


def context_for(session, actor_id: str) -> ActorContext:
    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    from sqlalchemy import select

    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


def test_grants_come_from_the_database(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            permissions = PermissionResolver(session).permissions_for("persona_data_steward")
            assert "registry.crosswalk.propose" in permissions
            assert "registry.crosswalk.decide" in permissions
            assert "permit.decide" not in permissions
            assert "finance.allocation.confirm" not in permissions
    finally:
        factory.dispose()


def test_administrator_configuration_grants_no_business_approval(seeded: Settings) -> None:
    """Administrator membership never implies a business approval."""
    bundle = FixtureBundle.load()
    administrator_role = next(
        role for role in bundle.actors.roles if role.role_id == "administrator"
    )
    for forbidden in (
        "permit.decide",
        "permit.issue",
        "finance.allocation.confirm",
        "registry.crosswalk.decide",
        "rule.version.publish",
        "governance.authority_policy.publish",
    ):
        assert forbidden not in administrator_role.permission_ids

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            permissions = PermissionResolver(session).permissions_for(
                "persona_city_administrator"
            )
            assert "records.configuration.view" in permissions
            # Reviewer and issuing authority are not part of the administrator.
            assert "permit.decide" not in permissions
            assert "permit.issue" not in permissions
    finally:
        factory.dispose()


def test_domain_scope_limits_a_grant(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            resolver = PermissionResolver(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            assert resolver.allows(
                reviewer, "permit.decide", ResourceContext(domain_id="permits")
            )
            assert not resolver.allows(
                reviewer, "permit.decide", ResourceContext(domain_id="finance")
            )
            steward = context_for(session, "persona_data_steward")
            assert resolver.allows(
                steward, "source.record.update", ResourceContext(domain_id="applicants")
            )
            assert not resolver.allows(
                steward, "source.record.update", ResourceContext(domain_id=None)
            )
    finally:
        factory.dispose()


def test_record_scope_limits_an_applicant(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            resolver = PermissionResolver(session)
            actor = context_for(session, "persona_applicant")
            assert resolver.allows(
                actor,
                "applicant.profile.edit",
                ResourceContext(domain_id="applicants", record_ids=("party_applicant_1",)),
            )
            assert not resolver.allows(
                actor,
                "applicant.profile.edit",
                ResourceContext(domain_id="applicants", record_ids=("party_applicant_2",)),
            )
    finally:
        factory.dispose()


def test_authorize_raises_for_an_ungranted_action(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            resolver = PermissionResolver(session)
            actor = context_for(session, "persona_applicant")
            with pytest.raises(PermissionDeniedError):
                resolver.authorize(
                    actor, "permit.decide", ResourceContext(domain_id="permits")
                )
    finally:
        factory.dispose()


def test_a_role_label_never_authorizes(seeded: Settings) -> None:
    """A client-supplied role inside the context grants nothing."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            resolver = PermissionResolver(session)
            forged = ActorContext(
                actor_id="persona_applicant",
                role_ids=frozenset({"administrator", "permit_reviewer", "data_owner"}),
                domain_scope=frozenset({"permits", "finance"}),
                record_scope=frozenset(),
            )
            assert not resolver.allows(
                forged, "permit.decide", ResourceContext(domain_id="permits")
            )
            with pytest.raises(PermissionDeniedError):
                resolver.authorize(
                    forged, "permit.decide", ResourceContext(domain_id="permits")
                )
    finally:
        factory.dispose()


def test_an_inactive_actor_has_no_permissions(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            actor = session.get(Actor, "persona_data_steward")
            actor.active = False
        with factory() as session:
            resolver = PermissionResolver(session)
            context = context_for(session, "persona_data_steward")
            assert not resolver.allows(
                context, "source.record.update", ResourceContext(domain_id="applicants")
            )
    finally:
        factory.dispose()


def test_denied_error_carries_no_record_value(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            resolver = PermissionResolver(session)
            actor = context_for(session, "persona_applicant")
            with pytest.raises(PermissionDeniedError) as caught:
                resolver.authorize(
                    actor,
                    "finance.allocation.confirm",
                    ResourceContext(domain_id="finance", record_ids=("payment_d01_settled",)),
                )
            payload = caught.value.to_dict()
            assert payload["code"] == "permission_denied"
            assert "payment_d01_settled" not in str(payload)
    finally:
        factory.dispose()
