"""The built in mode migration widens the mode of a model run and no more."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from acme_city.core.config import Settings
from acme_city.persistence.session import initialize_database
from tests.support.migration_head import migration_head


def test_opr_builtin_mode_migration_allows_the_built_in_mode(tmp_path: Path) -> None:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'opr-builtin-mode.db'}",
            "ACME_SECRET_KEY": "opr-builtin-mode-test-secret",
        },
        key_file=tmp_path / "missing.env",
    )
    assert initialize_database(settings) == migration_head()
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            columns = {column["name"] for column in inspector.get_columns("model_runs")}
            ddl = connection.execute(
                text("SELECT sql FROM sqlite_master WHERE name = 'model_runs'")
            ).scalar_one()
    finally:
        engine.dispose()
    # The migration touches the mode of a model run and nothing else.
    assert "mode" in columns
    assert "builtin" in str(ddl)
    # The provider paths keep their modes.
    for mode in ("live", "replay", "cached"):
        assert mode in str(ddl)


def test_a_model_run_may_record_the_built_in_mode(tmp_path: Path) -> None:
    """The column accepts the new mode, so the built in run may be written."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'opr-builtin-write.db'}",
            "ACME_SECRET_KEY": "opr-builtin-write-test-secret",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO model_runs (mode, provider, model, prompt_version, "
                    "schema_version, started_at, id, version, correlation_id, created_at) "
                    "VALUES ('builtin', 'builtin', 'builtin-rules-1', 'p', 's', "
                    "'2026-10-29 00:00:00', 'modelrun_builtin_probe', 1, 'corr', "
                    "'2026-10-29 00:00:00')"
                )
            )
    finally:
        engine.dispose()
