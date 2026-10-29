"""Migration contract for the steward registry automation schema."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from acme_city.core.config import Settings
from acme_city.persistence.session import initialize_database

TABLES = {
    "registry_automation_policies",
    "registry_automation_jobs",
    "registry_automation_evaluations",
    "registry_automation_applications",
}


def settings_for(tmp_path) -> Settings:
    return Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'autolink.db'}",
            "ACME_SECRET_KEY": "autolink-migration-test-secret",
        },
        key_file=tmp_path / "missing.env",
    )


def test_migration_creates_registry_automation_tables_and_no_rows(tmp_path) -> None:
    settings = settings_for(tmp_path)
    assert initialize_database(settings) == "stw_registry_automation"
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect() as connection:
            assert TABLES <= set(inspect(connection).get_table_names())
            for table in TABLES:
                assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
    finally:
        engine.dispose()


def test_policy_and_job_defaults_are_safe(tmp_path) -> None:
    settings = settings_for(tmp_path)
    initialize_database(settings)
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                """
                INSERT INTO registry_automation_policies
                  (id, matcher_version, thresholds, source_scopes, reason, recorded_by_actor_id)
                VALUES
                  ('policy_test', 'registry-v1', '{}', '[]', 'preview only', 'actor_steward')
                """
            ))
            row = connection.execute(text(
                "SELECT mode, status, version FROM registry_automation_policies WHERE id='policy_test'"
            )).one()
            assert tuple(row) == ("paused", "draft", 1)
    finally:
        engine.dispose()
