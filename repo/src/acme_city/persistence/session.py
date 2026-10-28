"""Engine and session management.

The application uses one SQLite database.  Foreign key enforcement is switched
on for every connection, because SQLite ignores foreign keys by default and the
schema relies on validated references between aggregates.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from acme_city.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_FACTORIES: dict[str, "SessionFactory"] = {}


class SessionFactory:
    """Creates sessions bound to one database URL."""

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        self.database_url = database_url
        self._engine = create_engine(
            database_url,
            echo=echo,
            future=True,
            connect_args=_connect_args(database_url),
        )
        _enable_sqlite_foreign_keys(self._engine)
        self._sessionmaker = sessionmaker(
            bind=self._engine, expire_on_commit=False, autoflush=False, future=True
        )

    @property
    def engine(self) -> Engine:
        return self._engine

    def __call__(self) -> Session:
        return self._sessionmaker()

    def dispose(self) -> None:
        self._engine.dispose()


def _connect_args(database_url: str) -> dict[str, Any]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    """Turn on SQLite foreign key enforcement for every connection."""

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def get_session_factory(database_url: str | None = None) -> SessionFactory:
    """Return the cached factory for ``database_url``."""
    url = database_url or os.environ.get("ACME_DATABASE_URL") or "sqlite:///var/acme_city.db"
    factory = _FACTORIES.get(url)
    if factory is None:
        factory = SessionFactory(url)
        _FACTORIES[url] = factory
    return factory


@contextmanager
def transaction(factory: SessionFactory | None = None) -> Iterator[Session]:
    """Yield a session inside a single transaction.

    The transaction commits when the block exits normally and rolls back when
    it raises.  Audit writes share this transaction with the business change
    they describe.
    """
    session = (factory or get_session_factory())()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def alembic_config(settings: Settings) -> Any:
    """Build an Alembic configuration for the configured database."""
    from alembic.config import Config

    ini_path = Path(os.environ.get("ACME_ALEMBIC_INI", DEFAULT_ALEMBIC_INI))
    if not ini_path.exists():  # pragma: no cover - packaging guard
        raise FileNotFoundError(f"alembic configuration not found: {ini_path}")
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(ini_path.parent / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def initialize_database(settings: Settings) -> str:
    """Create or upgrade the database to the latest migration.

    Returns the Alembic revision the database now carries.
    """
    from alembic import command

    config = alembic_config(settings)
    command.upgrade(config, "head")
    return current_revision(settings) or "unknown"


def current_revision(settings: Settings) -> str | None:
    """Return the Alembic revision recorded in the database, if any."""
    try:
        engine = create_engine(
            settings.database_url, future=True, connect_args=_connect_args(settings.database_url)
        )
    except Exception:  # pragma: no cover - invalid URL
        return None
    try:
        with engine.connect() as connection:
            row = connection.execute(text("SELECT version_num FROM alembic_version")).first()
    except Exception:
        return None
    finally:
        engine.dispose()
    return None if row is None else row[0]


@dataclass(frozen=True)
class DatabaseHealth:
    """Persistence health for the health endpoint.

    The database location and any secret never appear in this record.
    """

    reachable: bool
    state: str
    revision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"reachable": self.reachable, "state": self.state, "revision": self.revision}


def expected_head_revision(settings: Settings) -> str | None:
    """Return the single Alembic head revision this build expects."""
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(alembic_config(settings)).get_heads()
    return heads[0] if len(heads) == 1 else None


def database_is_demo(engine: Engine) -> bool:
    """Return whether the database carries the fictional-demo marker."""
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text(
                    "SELECT COUNT(*) FROM sqlite_master "
                    "WHERE type='table' AND name='demo_environment'"
                )
            ).scalar_one()
            if not exists:
                return False
            flagged = connection.execute(
                text("SELECT COUNT(*) FROM demo_environment WHERE fictional_demo = 1")
            ).scalar_one()
            return bool(flagged)
    except Exception:
        return False


def database_health(settings: Settings, *, engine: Engine | None = None) -> DatabaseHealth:
    """Report whether the database is reachable and up to date with migrations.

    Args:
        settings: The configured settings.  The database location is never
            reported back to a caller.
        engine: An existing engine to reuse.  One is created and disposed when
            no engine is supplied.
    """
    owned = engine is None
    try:
        if engine is None:
            engine = create_engine(
                settings.database_url,
                future=True,
                connect_args=_connect_args(settings.database_url),
            )
    except Exception:
        return DatabaseHealth(reachable=False, state="unreachable")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            has_alembic = connection.execute(
                text(
                    "SELECT COUNT(*) FROM sqlite_master "
                    "WHERE type='table' AND name='alembic_version'"
                )
            ).scalar_one()
    except Exception:
        return DatabaseHealth(reachable=False, state="unreachable")
    finally:
        if owned:
            engine.dispose()

    if not has_alembic:
        return DatabaseHealth(reachable=True, state="uninitialized")
    revision = current_revision(settings)
    if revision is None:
        return DatabaseHealth(reachable=True, state="uninitialized")
    return DatabaseHealth(reachable=True, state="current", revision=revision)


__all__ = [
    "DatabaseHealth",
    "SessionFactory",
    "alembic_config",
    "current_revision",
    "database_health",
    "database_is_demo",
    "expected_head_revision",
    "get_session_factory",
    "initialize_database",
    "transaction",
]
