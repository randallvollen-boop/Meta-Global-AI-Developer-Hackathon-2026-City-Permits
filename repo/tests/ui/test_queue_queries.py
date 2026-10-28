"""The work queue loads its assessments in bulk, not once per application."""
# REQUIRES: UX-01
# The queue builder issues one assessment query however many applications it shows.

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import event

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui import view_models

ASSESSMENT_TABLE = "assessments"


@pytest.fixture()
def factory(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'queue-queries.db'}",
            "ACME_SECRET_KEY": "queue-queries-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    session_factory = SessionFactory(settings.database_url)
    with transaction(session_factory) as session:
        session.add(
            DemoEnvironment(
                id="demo_environment_local",
                environment_id=ENVIRONMENT_ID,
                fictional_demo=True,
                fixture_version=bundle.fixture_version,
                label="local fictional demonstration",
            )
        )
    with transaction(session_factory) as session:
        reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    yield session_factory
    session_factory.dispose()


def _actor(session, actor_id: str, record_scope: frozenset[str] = frozenset()) -> ActorContext:
    grants = PermissionResolver(session).grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        domain_scope=frozenset(g.domain_id for g in grants if g.domain_id),
        record_scope=record_scope,
    )


def _count(factory: SessionFactory, run) -> dict[str, int]:
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    event.listen(factory.engine, "before_cursor_execute", record)
    try:
        run()
    finally:
        event.remove(factory.engine, "before_cursor_execute", record)
    return {
        "total": len(statements),
        "assessment": sum(
            1 for s in statements if f"FROM {ASSESSMENT_TABLE} " in s or f"FROM {ASSESSMENT_TABLE}\n" in s
        ),
    }


def test_assessments_are_loaded_in_one_query_for_n_applications(factory: SessionFactory) -> None:
    with factory() as session:
        full = _actor(session, "persona_permit_reviewer")
        total_apps = len(view_models.visible_applications(session, full))
        assert total_apps >= 10, "the fixture should give the queue a realistic N"
        one_id = view_models.visible_applications(session, full)[0].id
        single = _actor(session, "persona_permit_reviewer", frozenset({one_id}))
        assert len(view_models.visible_applications(session, single)) == 1

        counted_one = _count(factory, lambda: view_models.work_queue(session, single))
        counted_all = _count(factory, lambda: view_models.work_queue(session, full))

    assert counted_one["assessment"] <= 1
    assert counted_all["assessment"] == 1, counted_all
    # Permit-type and icon lookups are shared between applications of one type
    # too, so the total grows by well under the ~19 queries per application the
    # queue used to issue (231 queries for 13 applications, before the change
    # it was 251).
    per_extra_application = (counted_all["total"] - counted_one["total"]) / (total_apps - 1)
    assert per_extra_application < 18, (counted_one, counted_all, total_apps)


def test_queue_financial_state_matches_a_per_application_lookup(factory: SessionFactory) -> None:
    """The bulk lookup picks the same assessment the old per-application query did."""
    from sqlalchemy import select

    from acme_city.persistence.models import finance

    with factory() as session:
        actor = _actor(session, "persona_permit_reviewer")
        entries = view_models.work_queue(session, actor)["entries"]
        applications = [e for e in entries if e["kind"] == "application"]
        assert applications
        for entry in applications:
            row = session.execute(
                select(finance.Assessment)
                .where(
                    finance.Assessment.application_id == entry["id"],
                    finance.Assessment.status == "current",
                )
                .order_by(finance.Assessment.version.desc())
            ).scalars().first()
            expected = (
                f"assessed {row.assessed_total_cents / 100:.2f} {row.currency}"
                if row is not None
                else "not assessed"
            )
            assert entry["financial_state"] == expected
        assert any(e["financial_state"] != "not assessed" for e in applications)
