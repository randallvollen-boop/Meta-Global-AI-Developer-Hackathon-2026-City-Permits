"""The work-queue migration creates only its declared table."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

from acme_city.core.config import Settings
from acme_city.persistence.session import initialize_database
from tests.support.migration_head import migration_head


def test_opr_work_queue_migration_creates_the_queue_table(tmp_path: Path) -> None:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'opr-work-queue.db'}",
            "ACME_SECRET_KEY": "opr-work-queue-test-secret",
        },
        key_file=tmp_path / "missing.env",
    )
    assert initialize_database(settings) == migration_head()
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            columns = {column["name"] for column in inspector.get_columns("agent_work_queue")}
            indexes = inspector.get_indexes("agent_work_queue")
    finally:
        engine.dispose()
    assert {
        "work_key",
        "application_id",
        "agent_key",
        "status",
        "attempts",
        "claimed_at",
        "finished_at",
        "version",
    } <= columns
    # The work identity is unique, so the same work is never queued twice.
    assert any(
        index["unique"] and index["column_names"] == ["work_key"] for index in indexes
    )
    # The queue keeps a status column and an attempt count.  It holds no lease
    # and no fencing token.
    assert not {"lease_expires_at", "lease_owner", "fencing_token"} & columns
