"""The demo scenario clock.

In the fictional demo, ages, service targets, overdue flags and dashboards read
against one demo date.  Stored data, the rule and fee version of a case and the
real clock of every other run stay as they were.
"""
# REQUIRES: UX-01, PER-03
# The clock is off by default, applies to a marked fictional demo only, changes
# no stored row and no selected rule or fee version.

from __future__ import annotations

import html
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core import clock
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.scenario_clock import (
    AUTO_LEAD_DAYS,
    LABEL_HELP,
    demo_date_label,
    resolve_scenario_moment,
)
from acme_city.fixtures.synthetic import load_synthetic_year
from acme_city.ops.dashboard import dashboard
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.queues import intake_queue
from acme_city.rules.service import RuleCatalogService as RuleService


def context_for(session, actor_id: str) -> ActorContext:
    """Return the server-resolved context of a seeded persona."""
    grants = PermissionResolver(session).grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(record_id for grant in grants for record_id in grant.record_scope),
    )


@pytest.fixture(autouse=True)
def _real_clock_after() -> None:
    clock.set_scenario_clock(None)
    yield
    clock.set_scenario_clock(None)


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """A reset fictional demo database that also holds a small synthetic year."""
    tmp = tmp_path_factory.mktemp("scenario_clock")
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp / 'clock.db'}",
            "ACME_SECRET_KEY": "scenario-clock-secret-value",
        },
        key_file=tmp / "missing.env",
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
        with transaction(factory) as session:
            load_synthetic_year(session, seed=20261028, count=60)
    finally:
        factory.dispose()
    return settings


def _seeded_latest(session) -> datetime:
    value = session.execute(
        select(func.max(permit.Application.initial_submitted_at)).where(
            permit.Application.scenario_id.is_not(None),
            permit.Application.synthetic.is_(False),
        )
    ).scalar_one()
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def test_the_real_clock_is_the_default(demo: Settings) -> None:
    assert clock.scenario_moment() is None
    assert abs((clock.app_now() - clock.utc_now()).total_seconds()) < 5
    assert Settings.load(environ={"ACME_SECRET_KEY": "x" * 20}, key_file=Path("/nonexistent")).scenario_clock == ""
    factory = SessionFactory(demo.database_url)
    try:
        with factory() as session:
            assert resolve_scenario_moment(session, "") is None
            assert resolve_scenario_moment(session, "off") is None
    finally:
        factory.dispose()


def test_an_explicit_date_and_auto_choose_one_moment(demo: Settings) -> None:
    factory = SessionFactory(demo.database_url)
    try:
        with factory() as session:
            explicit = resolve_scenario_moment(session, "2026-10-14")
            assert explicit == datetime(2026, 10, 14, 17, tzinfo=UTC)
            latest = _seeded_latest(session)
            far_future = latest + timedelta(days=90)
            auto = resolve_scenario_moment(session, "auto", real_now=far_future)
            assert auto == latest + timedelta(days=AUTO_LEAD_DAYS)
            # The most recent demo case is a few days old, never negative.
            assert timedelta(days=AUTO_LEAD_DAYS) == auto - latest
            # The synthetic year (submitted later) does not move the date.
            latest_synthetic = session.execute(
                select(func.max(permit.Application.initial_submitted_at)).where(permit.Application.synthetic.is_(True))
            ).scalar_one()
            assert latest_synthetic.replace(tzinfo=UTC) > latest
            # Never later than the real clock.
            early = latest - timedelta(days=1)
            assert resolve_scenario_moment(session, "auto", real_now=early) == early
            with pytest.raises(ValueError):
                resolve_scenario_moment(session, "yesterday")
    finally:
        factory.dispose()


def test_a_database_that_is_not_the_fictional_demo_ignores_the_setting(demo: Settings) -> None:
    factory = SessionFactory(demo.database_url)
    try:
        with factory() as session:
            marker = session.execute(select(DemoEnvironment)).scalar_one()
            marker.fictional_demo = False
            session.flush()
            assert resolve_scenario_moment(session, "auto") is None
            assert resolve_scenario_moment(session, "2026-10-14") is None
            session.rollback()
    finally:
        factory.dispose()


def test_the_label_and_help_read_plainly() -> None:
    moment = datetime(2026, 10, 4, 17, tzinfo=UTC)
    assert demo_date_label(moment) == "Demo date: 4 Oct 2026"
    assert demo_date_label(None) == ""
    for text in (demo_date_label(moment), LABEL_HELP):
        assert not re.search(r"[–—]|--| - ", text)
    assert "demo date" in LABEL_HELP


def test_the_app_installs_the_clock_only_when_asked(demo: Settings) -> None:
    off = create_app(demo)
    assert clock.scenario_moment() is None
    on = create_app(demo.model_copy(update={"scenario_clock": "2026-10-14"}))
    assert clock.scenario_moment() == datetime(2026, 10, 14, 17, tzinfo=UTC)
    # A later app without the setting clears it again (no leak between apps).
    create_app(demo)
    assert clock.scenario_moment() is None
    assert off is not on


def test_the_top_bar_shows_the_label_only_on_the_scenario_clock(demo: Settings) -> None:
    for setting, expected in (("", False), ("2026-10-14", True)):
        app = create_app(demo.model_copy(update={"scenario_clock": setting}))
        with TestClient(app) as client:
            response = client.get("/select")
            assert response.status_code == 200
            assert ("Demo date: 14 Oct 2026" in response.text) is expected
            assert ('data-testid="demo-date"' in response.text) is expected
            if expected:
                assert html.escape(LABEL_HELP) in response.text


def test_ages_overdue_flags_and_the_dashboard_use_the_scenario_clock(demo: Settings) -> None:
    factory = SessionFactory(demo.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            moment = resolve_scenario_moment(session, "2026-10-08")
            real_rows = {r["reference"]: r for r in intake_queue(session, steward)["rows"]}
            average_real = next(m for m in dashboard(session, synthetic="exclude")["figures"] if m["key"] == "average_age")
            clock.set_scenario_clock(moment)
            rows = {r["reference"]: r for r in intake_queue(session, steward)["rows"]}
            average_demo = next(m for m in dashboard(session, synthetic="exclude")["figures"] if m["key"] == "average_age")
            included = dashboard(session, synthetic="include")
            applications = {
                a.source_application_number: a
                for a in session.execute(select(permit.Application)).scalars().all()
            }
        assert rows and set(rows) == set(real_rows)
        for reference, row in rows.items():
            submitted = applications[reference].initial_submitted_at
            submitted = submitted if submitted.tzinfo else submitted.replace(tzinfo=UTC)
            assert row["age_days"] == max((moment - submitted).days, 0)
            target = row["service_target_days"]
            expected_tone = "over" if target and row["age_days"] > target else ("at" if target and row["age_days"] == target else "")
            assert row["age_tone"] == expected_tone
        # Cases seeded before the demo date are younger than on the real clock.
        assert any(rows[r]["age_days"] < real_rows[r]["age_days"] for r in rows)
        assert average_demo["value"] != average_real["value"]
        assert "2026-10-08" in average_demo["definition"]
        # The synthetic year is read on the real clock, never the demo date.
        assert included["as_of"][:10] == clock.utc_now().date().isoformat()
        # The workspace helpers read the same clock.
        from acme_city.ui import reviewer_views, view_models
        submitted = datetime(2026, 10, 1, 9, tzinfo=UTC)
        assert view_models._age_days(submitted) == 7
        assert "8 Oct 2026" in reviewer_views.scenario_clock_note(moment) or "2026-10-08" in reviewer_views.scenario_clock_note(moment)
        assert not re.search(r"[\u2013\u2014]| - ", reviewer_views.scenario_clock_note(moment))
    finally:
        factory.dispose()


def test_the_scenario_clock_changes_no_stored_row_and_no_version(demo: Settings) -> None:
    """Every demo case resolves the same rule and fee version before and after."""
    factory = SessionFactory(demo.database_url)
    try:
        with factory() as session:
            applications = session.execute(select(permit.Application)).scalars().all()
            types = {
                t.permit_type_id: t.key for t in session.execute(select(permit.PermitType)).scalars().all()
            }
            stored_before = sorted((a.id, a.initial_submitted_at, a.status) for a in applications)

            def resolved() -> dict[str, tuple]:
                service = RuleService(session)
                out = {}
                for a in applications:
                    key = types[a.permit_type_id]
                    basis = a.initial_submitted_at if a.initial_submitted_at.tzinfo else a.initial_submitted_at.replace(tzinfo=UTC)
                    rules = service.resolve("executable", key, basis)
                    fees = service.resolve("fee_schedule", key, basis)
                    out[a.id] = (
                        tuple(sorted((r.rule_id, r.version) for r in rules.rules)),
                        None if fees.fee_schedule is None else (fees.fee_schedule.fee_schedule_id, fees.fee_schedule.version_label),
                    )
                return out

            before = resolved()
            clock.set_scenario_clock(datetime(2026, 10, 8, 17, tzinfo=UTC))
            after = resolved()
            assert len(before) == len(applications) > 60
            assert before == after
            flipped = [k for k in before if before[k] != after[k]]
            assert flipped == []
            assert any(v[1] is not None for v in before.values())
            session.expire_all()
            stored_after = sorted(
                (a.id, a.initial_submitted_at, a.status)
                for a in session.execute(select(permit.Application)).scalars().all()
            )
            assert stored_before == stored_after
            print(f"scenario clock version check: {len(before)} cases, 0 flipped")
    finally:
        factory.dispose()


def test_the_seeded_queue_reads_naturally_on_the_auto_demo_date(demo: Settings) -> None:
    """Most seeded cases sit inside their target, a few are near it, a few are over."""
    factory = SessionFactory(demo.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            clock.set_scenario_clock(resolve_scenario_moment(session, "auto"))
            rows = intake_queue(session, steward)["rows"]
    finally:
        factory.dispose()
    assert len(rows) == 12
    youngest = min(r["age_days"] for r in rows)
    assert youngest == AUTO_LEAD_DAYS
    over = [r for r in rows if r["age_tone"] == "over"]
    near = [r for r in rows if r["age_tone"] == "at" or 0 <= r["service_target_days"] - r["age_days"] <= 1]
    within = [r for r in rows if r["age_tone"] == "" and r not in near]
    assert 2 <= len(over) <= 3
    assert 2 <= len(near) <= 3
    assert len(within) > len(over) + len(near)


def test_respaced_seed_dates_keep_every_rule_and_fee_window(demo: Settings) -> None:
    """Every seeded submission stays inside the one window where the first versions apply.

    All published rule and fee versions start on 2026-01-01 except the second
    versions, which start on 2026-11-01.  A seeded case dated between the two
    resolves the same versions as on its original date.
    """
    factory = SessionFactory(demo.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(permit.Application).where(permit.Application.synthetic.is_(False))
            ).scalars().all()
            assert len(rows) == 13
            for row in rows:
                when = row.initial_submitted_at.replace(tzinfo=UTC)
                assert datetime(2026, 1, 1, tzinfo=UTC) <= when < datetime(2026, 11, 1, tzinfo=UTC)
    finally:
        factory.dispose()
