"""The processing-policy migration creates its one persisted policy table."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

from acme_city.core.config import Settings
from acme_city.persistence.session import initialize_database


def test_opr_processing_policy_migration_creates_the_policy_table(tmp_path: Path) -> None:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'opr-policy.db'}",
            "ACME_SECRET_KEY": "opr-policy-test-secret",
        },
        key_file=tmp_path / "missing.env",
    )
    assert initialize_database(settings) == "opr_processing_policy"
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect() as connection:
            columns = {column["name"] for column in inspect(connection).get_columns("agent_processing_policies")}
    finally:
        engine.dispose()
    assert {"mode", "runs_per_hour", "max_batch_size", "version"} <= columns
