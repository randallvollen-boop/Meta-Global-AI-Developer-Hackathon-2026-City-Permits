"""Migration tests: upgrade from empty, downgrade, and metadata agreement."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import create_engine, inspect, text

from acme_city.core.config import Settings
from acme_city.persistence.base import Base
from acme_city.persistence.session import (
    alembic_config,
    current_revision,
    initialize_database,
)


def make_settings(tmp_path: Path, name: str = "migrations.db") -> Settings:
    return Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / name}",
            "ACME_SECRET_KEY": "migration-test-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )


def test_upgrade_from_empty_database_creates_the_schema(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    revision = initialize_database(settings)
    # Head is 0009 since the P3insight migration (synthetic flags and business categories); the brief adds it
    # deliberately, so the expected head moved with the schema.
    assert revision == "0009"

    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            recorded = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()

    assert "alembic_version" in tables
    assert recorded == "0009"
    assert set(Base.metadata.tables) <= tables


def test_downgrade_and_upgrade_again_on_a_disposable_database(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "cycle.db")
    config = alembic_config(settings)

    command.upgrade(config, "head")
    assert current_revision(settings) == "0009"

    command.downgrade(config, "base")
    assert current_revision(settings) is None

    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
    finally:
        engine.dispose()
    assert "applications" not in tables

    command.upgrade(config, "head")
    assert current_revision(settings) == "0009"


def test_alembic_check_reports_no_ungenerated_changes(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "check.db")
    config = alembic_config(settings)
    command.upgrade(config, "head")
    # ``check`` raises SystemExit(0) when the database matches the models.
    command.check(config)


def test_migration_creates_no_rows_by_itself(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "empty.db")
    initialize_database(settings)
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect() as connection:
            actors = connection.execute(text("SELECT COUNT(*) FROM actors")).scalar_one()
            domains = connection.execute(text("SELECT COUNT(*) FROM domains")).scalar_one()
    finally:
        engine.dispose()
    assert actors == 0
    assert domains == 0
