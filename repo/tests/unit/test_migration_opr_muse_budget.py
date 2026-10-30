"""The Muse budget migration creates only its declared table."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

from acme_city.core.config import Settings
from acme_city.persistence.session import initialize_database
from tests.support.migration_head import migration_head


def test_opr_muse_budget_migration_creates_the_budget_table(tmp_path: Path) -> None:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'opr-muse-budget.db'}",
            "ACME_SECRET_KEY": "opr-muse-budget-test-secret",
        },
        key_file=tmp_path / "missing.env",
    )
    assert initialize_database(settings) == migration_head()
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            columns = {column["name"] for column in inspector.get_columns("muse_daily_budget")}
            indexes = inspector.get_indexes("muse_daily_budget")
    finally:
        engine.dispose()
    assert {"day", "calls_used", "id", "created_at"} <= columns
    # One row per day: the day is the identity of the allowance.
    assert any(
        index["unique"] and index["column_names"] == ["day"] for index in indexes
    )
