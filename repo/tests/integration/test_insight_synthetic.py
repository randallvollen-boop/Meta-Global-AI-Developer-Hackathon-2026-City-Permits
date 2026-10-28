"""Seeded synthetic history: flagged, kept apart, never in the default reset."""
# REQUIRES: UX-01, SEC-02

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from insight_support import SYNTHETIC_COUNT, build_environment, open_factory
from sqlalchemy import func, inspect, select, text

from acme_city.fixtures.synthetic import (
    backfill_business_categories,
    category_for_name,
    load_synthetic_year,
    remove_synthetic,
    synthetic_application_count,
)
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.persistence.base import Base
from acme_city.persistence.models import audit, permit, registry
from acme_city.persistence.session import transaction
from acme_city.ui.view_models import visible_applications

REPO_ROOT = Path(__file__).resolve().parents[2]

FLAGGED_TABLES = (
    "applications",
    "application_revisions",
    "application_parties",
    "application_sites",
    "decisions",
    "permits",
    "canonical_entities",
    "parties",
    "credentials",
)


def flag_counts(factory) -> dict[str, tuple[int, int]]:
    """Return (synthetic, not synthetic) row counts per flagged table."""
    out: dict[str, tuple[int, int]] = {}
    with transaction(factory) as session:
        for table in FLAGGED_TABLES:
            flagged = session.execute(text(f"SELECT COUNT(*) FROM {table} WHERE synthetic = 1")).scalar_one()
            plain = session.execute(text(f"SELECT COUNT(*) FROM {table} WHERE synthetic = 0")).scalar_one()
            out[table] = (flagged, plain)
    return out


@pytest.fixture(scope="module")
def fixtures_only(tmp_path_factory):
    return build_environment(tmp_path_factory.mktemp("fx"), synthetic=False, name="fx.db")


@pytest.fixture(scope="module")
def with_synthetic(tmp_path_factory):
    return build_environment(tmp_path_factory.mktemp("syn"), synthetic=True, name="syn.db")


def test_the_default_reset_loads_no_synthetic_row(fixtures_only) -> None:
    factory = open_factory(fixtures_only)
    try:
        counts = flag_counts(factory)
        assert all(flagged == 0 for flagged, _ in counts.values()), counts
        with transaction(factory) as session:
            assert synthetic_application_count(session) == 0
            assert session.execute(select(func.count()).select_from(permit.Application)).scalar_one() == 13
    finally:
        factory.dispose()


def test_every_flagged_table_has_a_synthetic_column(fixtures_only) -> None:
    factory = open_factory(fixtures_only)
    try:
        with factory.engine.connect() as connection:
            names = inspect(connection).get_table_names()
            for table in FLAGGED_TABLES:
                assert table in names
                columns = {c["name"] for c in inspect(connection).get_columns(table)}
                assert "synthetic" in columns, table
        assert {t.name for t in Base.metadata.sorted_tables} >= set(FLAGGED_TABLES)
    finally:
        factory.dispose()


def test_every_generated_row_is_flagged_and_every_fixture_row_is_not(
    fixtures_only, with_synthetic
) -> None:
    base_factory = open_factory(fixtures_only)
    full_factory = open_factory(with_synthetic)
    try:
        base = flag_counts(base_factory)
        full = flag_counts(full_factory)
        for table in FLAGGED_TABLES:
            # The fixture rows are exactly the rows that are not flagged.
            assert full[table][1] == base[table][1], table
            assert full[table][0] > 0, table
        assert full["applications"][0] == SYNTHETIC_COUNT
        with transaction(full_factory) as session:
            scenario_ids = set(
                session.execute(
                    select(permit.Application.scenario_id).where(permit.Application.synthetic.is_(True))
                ).scalars()
            )
            assert scenario_ids == {"SYNTH"}
            populations = set(
                session.execute(
                    select(permit.Application.synthetic_population).where(permit.Application.synthetic.is_(True))
                ).scalars()
            )
            assert populations == {"synthetic-year-v1"}
            assert session.execute(
                select(func.count())
                .select_from(permit.Application)
                .where(permit.Application.synthetic.is_(False), permit.Application.scenario_id == "SYNTH")
            ).scalar_one() == 0
    finally:
        base_factory.dispose()
        full_factory.dispose()


def test_loading_writes_no_audit_event_and_changes_no_fixture_row(
    tmp_path, fixtures_only
) -> None:
    settings = build_environment(tmp_path, synthetic=False, name="before-after.db")
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            before_audit = session.execute(select(func.count()).select_from(audit.AuditEvent)).scalar_one()
            before_apps = {
                row.id: (row.status, row.version, row.source_application_number)
                for row in session.execute(select(permit.Application)).scalars()
            }
            before_decisions = session.execute(select(func.count()).select_from(permit.Decision)).scalar_one()
        with transaction(factory) as session:
            result = load_synthetic_year(session, seed=7, count=60)
        assert result["written"]["applications"] == 60
        with transaction(factory) as session:
            assert session.execute(select(func.count()).select_from(audit.AuditEvent)).scalar_one() == before_audit
            after_apps = {
                row.id: (row.status, row.version, row.source_application_number)
                for row in session.execute(
                    select(permit.Application).where(permit.Application.synthetic.is_(False))
                ).scalars()
            }
            assert after_apps == before_apps
            # The decisions of the loader name no person and no agent.
            actors = set(
                session.execute(
                    select(permit.Decision.decided_by_actor_id).where(permit.Decision.synthetic.is_(True))
                ).scalars()
            )
            assert actors == {"synthetic_history"}
            assert session.execute(select(func.count()).select_from(permit.Decision).where(
                permit.Decision.synthetic.is_(False))).scalar_one() == before_decisions
    finally:
        factory.dispose()


def test_a_second_load_is_refused_and_removal_restores_the_fixtures(tmp_path) -> None:
    settings = build_environment(tmp_path, synthetic=True, name="again.db")
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            with pytest.raises(RuntimeError):
                load_synthetic_year(session, seed=1, count=5)
        with transaction(factory) as session:
            removed = remove_synthetic(session)
        assert removed["applications"] == SYNTHETIC_COUNT
        counts = flag_counts(factory)
        assert all(flagged == 0 for flagged, _ in counts.values()), counts
        with transaction(factory) as session:
            assert session.execute(select(func.count()).select_from(permit.Application)).scalar_one() == 13
    finally:
        factory.dispose()


def actor_for(session, actor_id: str) -> ActorContext:
    grants = PermissionResolver(session).grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        role_ids=frozenset(),
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(r for grant in grants for r in grant.record_scope),
    )


def test_synthetic_rows_never_enter_a_work_queue(with_synthetic) -> None:
    factory = open_factory(with_synthetic)
    try:
        with transaction(factory) as session:
            for actor_id in (
                "persona_data_steward",
                "persona_permit_reviewer",
                "persona_city_administrator",
            ):
                rows = visible_applications(session, actor_for(session, actor_id))
                assert len(rows) == 13, actor_id
                assert not any(row.synthetic for row in rows)
            from acme_city.agents.intake import waiting_applications

            assert not any(row.synthetic for row in waiting_applications(session))
    finally:
        factory.dispose()


def test_the_reset_backfills_the_categories_of_the_existing_businesses(fixtures_only) -> None:
    factory = open_factory(fixtures_only)
    try:
        with transaction(factory) as session:
            licences = {
                row.credential_id: row.business_category
                for row in session.execute(
                    select(registry.Credential).where(
                        registry.Credential.credential_type == "business_license"
                    )
                ).scalars()
            }
            assert licences == {
                "cred_license_cedarline": "restaurant",
                "cred_license_false_friend": "restaurant",
                "cred_license_quarry": "retail",
            }
            contractors = session.execute(
                select(registry.Credential.business_category).where(
                    registry.Credential.credential_type == "contractor_registration"
                )
            ).scalars().all()
            assert contractors and all(value is None for value in contractors)
            # The backfill only fills blanks, so a second run reports nothing.
            assert backfill_business_categories(session) == {"total": 0}
    finally:
        factory.dispose()


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("Gilded Heron Tavern", "bar"),
        ("Marrow Creek Grill", "restaurant"),
        ("Cedarline Coffee Roasters LLC", "restaurant"),
        ("Pennywhistle Goods", "retail"),
        ("Larchmont Realty Partners", "office"),
        ("Brightpath Fitness Studio", "other"),
    ],
)
def test_the_category_words(name: str, category: str) -> None:
    assert category_for_name(name) == category


def test_a_migration_backfills_existing_business_licences(tmp_path) -> None:
    from alembic import command

    from acme_city.core.config import Settings
    from acme_city.persistence.session import alembic_config

    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'upgrade.db'}",
            "ACME_SECRET_KEY": "migration-backfill-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    config = alembic_config(settings)
    command.upgrade(config, "0007")
    import sqlite3

    connection = sqlite3.connect(tmp_path / "upgrade.db")
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.execute(
        "INSERT INTO canonical_entities (id, entity_id, entity_type, label, status, created_at) "
        "VALUES ('entity_a','party_a','party','x','active','2026-01-01')"
    )
    for party_id, name in (("party_a", "Oak Street Tavern LLC"), ("party_b", "Mill Pond Bakery LLC"), ("party_c", "Zed Holdings")):
        connection.execute(
            "INSERT INTO parties (id, entity_id, party_type, display_name, status, version, created_at) "
            f"VALUES ('{party_id}','party_a','organization','{name}','active',1,'2026-01-01')"
        )
        connection.execute(
            "INSERT INTO credentials (id, credential_id, holder_party_id, credential_type, issuing_authority_id, "
            "number, status, version, created_at) "
            f"VALUES ('cred_{party_id}','cred_{party_id}','{party_id}','business_license','x','N-{party_id}','active',1,'2026-01-01')"
        )
    connection.execute(
        "INSERT INTO credentials (id, credential_id, holder_party_id, credential_type, issuing_authority_id, "
        "number, status, version, created_at) VALUES "
        "('cred_ctr','cred_ctr','party_a','contractor_registration','x','C-1','active',1,'2026-01-01')"
    )
    connection.commit()
    connection.close()
    command.upgrade(config, "head")
    connection = sqlite3.connect(tmp_path / "upgrade.db")
    rows = dict(connection.execute("SELECT id, business_category FROM credentials").fetchall())
    connection.close()
    assert rows == {
        "cred_party_a": "bar",
        "cred_party_b": "restaurant",
        "cred_party_c": "other",
        "cred_ctr": None,
    }


def test_the_demo_synthetic_prepare_mode_loads_the_year_on_top_of_the_fixtures(tmp_path) -> None:
    database = tmp_path / "demo.db"
    environment = os.environ.copy()
    environment["ACME_SECRET_KEY"] = "demo-synthetic-prep-secret-value"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "prepare_user_test.py"),
            "--mode",
            "demo-synthetic",
            "--database",
            f"sqlite:///{database}",
            "--record",
            str(tmp_path / "process.json"),
            "--state-file",
            str(tmp_path / "state.json"),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--synthetic-seed",
            "99",
            "--synthetic-count",
            "45",
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["mode"] == "demo-synthetic"
    assert state["model_mode"] == "none"
    assert state["server_running"] is False
    assert "synthetic" in state["label"]
    import sqlite3

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM applications WHERE synthetic = 1").fetchone()[0] == 45
        assert connection.execute("SELECT COUNT(*) FROM applications WHERE synthetic = 0").fetchone()[0] == 13
    finally:
        connection.close()
    # The default modes still load nothing synthetic.
    fresh = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "prepare_user_test.py"),
            "--mode",
            "fresh",
            "--database",
            f"sqlite:///{database}",
            "--record",
            str(tmp_path / "process.json"),
            "--state-file",
            str(tmp_path / "state-fresh.json"),
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert fresh.returncode == 0, fresh.stderr
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM applications WHERE synthetic = 1").fetchone()[0] == 0
    finally:
        connection.close()
