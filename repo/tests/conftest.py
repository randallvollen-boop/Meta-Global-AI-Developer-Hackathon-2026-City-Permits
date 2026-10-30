"""Suite-wide test support: migrate once, copy the schema for every test.

Almost every fixture builds a fresh SQLite file and calls ``initialize_database``,
which replays the whole Alembic chain (0001 to head) each time. That replay was
about 0.7 s per test and roughly 90% of the acceptance run.

This conftest runs the real chain once per test process into a template file and
gives each fresh SQLite database a copy of it. The template lives under pytest's
base temporary directory, which pytest prunes. Each test still owns its own file,
so isolation is unchanged. The chain itself stays covered: the template is a real
upgrade from empty, and ``tests/unit/test_migrations.py`` drives ``command.upgrade``
and ``command.downgrade`` directly.

Anything other than a new, empty SQLite file (an existing database, an in-memory
URL, another engine, a custom ``ACME_ALEMBIC_INI``) takes the original path.
Set ``ACME_TEST_FRESH_MIGRATIONS=1`` to switch the copy off and replay the chain
for every test.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from acme_city.core.config import Settings
from acme_city.persistence import session as _session

_SQLITE_FILE_PREFIX = "sqlite:///"
_original_initialize_database = _session.initialize_database
_template: Path | None = None
_template_root: Path | None = None


@pytest.hookimpl(trylast=True)
def pytest_configure(config) -> None:
    # Keep the template under pytest's own base directory. pytest keeps only the
    # last few of those, so a worker that is killed mid-run leaves nothing behind
    # for long.
    global _template_root
    _template_root = config._tmp_path_factory.mktemp("schema-template")


def _fresh_sqlite_path(settings: Settings) -> Path | None:
    url = settings.database_url
    if not url.startswith(_SQLITE_FILE_PREFIX) or "ACME_ALEMBIC_INI" in os.environ:
        return None
    raw = url[len(_SQLITE_FILE_PREFIX):]
    if not raw or raw.startswith(":memory:") or "?" in raw:
        return None
    path = Path(raw)
    if path.exists() and path.stat().st_size > 0:
        return None
    return path


def _template_database(settings: Settings) -> Path:
    global _template
    if _template is None:
        if _template_root is not None:
            directory = _template_root
        else:
            directory = Path(tempfile.mkdtemp(prefix="acme-schema-template-"))
            atexit.register(shutil.rmtree, directory, ignore_errors=True)
        template = directory / "template.db"
        _original_initialize_database(
            settings.model_copy(update={"database_url": f"{_SQLITE_FILE_PREFIX}{template}"})
        )
        _template = template
    return _template


def _copy_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def initialize_database(settings: Settings) -> str:
    target = _fresh_sqlite_path(settings)
    if target is None:
        return _original_initialize_database(settings)
    _copy_database(_template_database(settings), target)
    return _session.current_revision(settings) or "unknown"


if os.environ.get("ACME_TEST_FRESH_MIGRATIONS") != "1":
    _session.initialize_database = initialize_database
