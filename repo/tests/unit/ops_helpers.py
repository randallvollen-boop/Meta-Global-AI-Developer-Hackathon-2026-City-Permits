"""Shared set-up for the P3c operations tests: a reset demonstration database.

The database is reset once per test module and copied for every test, so a
test may break an invariant on purpose without touching another test.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.ids import new_id
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import audit, permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

ADMIN = "persona_city_administrator"


def settings_for(directory: Path, name: str) -> Settings:
    return Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{directory / name}",
            "ACME_SECRET_KEY": "ops-test-secret-value",
        },
        key_file=directory / "missing.env",
    )


def build_template(directory: Path) -> Path:
    """Reset a database once and return its file."""
    settings = settings_for(directory, "template.db")
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
    return directory / "template.db"


def copy_of(template: Path, directory: Path, name: str = "copy.db") -> Settings:
    """Return settings for a fresh copy of the template database."""
    shutil.copy(template, directory / name)
    return settings_for(directory, name)


def context_for(session, actor_id: str) -> ActorContext:
    """Return the server-resolved context of a seeded persona."""
    grants = PermissionResolver(session).grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(g.domain_id for g in grants if g.domain_id),
        record_scope=frozenset(r for g in grants for r in g.record_scope),
    )


def add_audit(session, *, action: str, target_type: str, target_id: str, actor_id: str = "persona_permit_reviewer") -> None:
    session.add(
        audit.AuditEvent(
            id=new_id("audit"),
            correlation_id=new_id("corr"),
            occurred_at=datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
            actor_id=actor_id,
            actor_role_ids=[],
            action=action,
            target_type=target_type,
            target_id=target_id,
            outcome="accepted",
        )
    )
    session.flush()


def add_decision(session, *, application_id: str = "app_d02", decided_by: str = "persona_permit_reviewer", outcome: str = "approved") -> permit.Decision:
    row = permit.Decision(
        id=new_id("decision"),
        application_id=application_id,
        decision_type="review",
        outcome=outcome,
        decided_by_actor_id=decided_by,
        decided_at=datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
        reason="a fictional test decision",
        status="current",
        stale=False,
    )
    session.add(row)
    session.flush()
    return row


def add_permit(session, *, decision: permit.Decision, issued_by: str = "persona_permit_reviewer") -> permit.Permit:
    row = permit.Permit(
        id=new_id("permit"),
        application_id=decision.application_id,
        decision_id=decision.id,
        permit_number=f"ACME-TEST-{new_id('n')[-6:]}",
        issued_at=datetime(2026, 10, 28, 13, 0, tzinfo=UTC),
        status="issued",
        snapshot={},
        artifact_hash="0" * 64,
        issuance_command_key=new_id("cmd"),
        issued_by_actor_id=issued_by,
        fictional_demo=True,
    )
    session.add(row)
    session.flush()
    return row
