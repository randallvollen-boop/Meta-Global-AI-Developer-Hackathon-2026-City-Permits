"""The operator-entitlement migration creates only its declared table."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

from acme_city.core.config import Settings
from acme_city.persistence.session import initialize_database


def test_opr_entitlement_migration_creates_the_entitlement_table(tmp_path: Path) -> None:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'opr-entitlement.db'}",
            "ACME_SECRET_KEY": "opr-entitlement-test-secret",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect() as connection:
            columns = {column["name"] for column in inspect(connection).get_columns("agent_role_entitlements")}
    finally:
        engine.dispose()
    assert {"role_id", "can_run_agents", "changed_by", "changed_at", "version"} <= columns
