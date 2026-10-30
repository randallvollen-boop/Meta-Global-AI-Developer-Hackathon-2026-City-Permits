"""Migration contract for the steward recommendation schema."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from acme_city.core.config import Settings
from acme_city.persistence.session import initialize_database
from tests.support.migration_head import migration_head

TABLE = "steward_recommendations"

INSERT = """
    INSERT INTO steward_recommendations
      (id, task_kind, task_id, record_version, outcome, confidence,
       evidence, reason, made_by_actor_id, made_at)
    VALUES
      ('stewrec_test', 'link', 'proposal_test', 3, 'confirm', 'high',
       '{}', 'The source names this master record.',
       'service_steward_assist', '2026-10-30 12:00:00')
"""


def settings_for(tmp_path) -> Settings:
    return Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'steward-recommendation.db'}",
            "ACME_SECRET_KEY": "steward-recommendation-migration-secret",
        },
        key_file=tmp_path / "missing.env",
    )


def test_migration_creates_the_recommendation_table_and_no_rows(tmp_path) -> None:
    settings = settings_for(tmp_path)
    assert initialize_database(settings) == migration_head()
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect() as connection:
            assert TABLE in set(inspect(connection).get_table_names())
            assert connection.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() == 0
    finally:
        engine.dispose()


def test_a_recommendation_holds_its_task_its_confidence_and_its_words(tmp_path) -> None:
    settings = settings_for(tmp_path)
    initialize_database(settings)
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text(INSERT))
            row = connection.execute(
                text(
                    """
                    SELECT task_kind, task_id, record_version, outcome, confidence,
                           reason, made_by_actor_id, cleared, cleared_at
                    FROM steward_recommendations WHERE id='stewrec_test'
                    """
                )
            ).one()
        assert tuple(row) == (
            "link",
            "proposal_test",
            3,
            "confirm",
            "high",
            "The source names this master record.",
            "service_steward_assist",
            0,
            None,
        )
    finally:
        engine.dispose()


def test_a_recommendation_of_an_unknown_confidence_is_refused(tmp_path) -> None:
    settings = settings_for(tmp_path)
    initialize_database(settings)
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.begin() as connection:
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        INSERT.replace("'high'", "'certain'").replace(
                            "stewrec_test", "stewrec_bad_confidence"
                        )
                    )
                )
    finally:
        engine.dispose()


def test_a_recommendation_of_an_unknown_outcome_is_refused(tmp_path) -> None:
    settings = settings_for(tmp_path)
    initialize_database(settings)
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.begin() as connection:
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        INSERT.replace("'confirm'", "'approve'").replace(
                            "stewrec_test", "stewrec_bad_outcome"
                        )
                    )
                )
    finally:
        engine.dispose()
