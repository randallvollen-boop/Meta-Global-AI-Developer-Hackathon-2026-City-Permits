"""Migration tests: upgrade from empty, downgrade, metadata agreement and the merge gates.

The single-head, unique-id and linear-chain tests are merge gates.  Migrations
after 0013 use non-numeric revision ids with matching file names; whoever merges
one sets its ``down_revision`` to the current head.  Each migration's own tests
go in ``tests/unit/test_migration_<id>.py``, never in this file.
"""

from __future__ import annotations

import ast
from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from acme_city.core.config import Settings
from acme_city.persistence.base import Base
from acme_city.persistence.session import (
    alembic_config,
    current_revision,
    initialize_database,
)


def script_head(settings: Settings) -> str:
    """Return the head revision of the migration scripts; lane migrations need no edit here."""
    head = ScriptDirectory.from_config(alembic_config(settings)).get_current_head()
    assert head is not None
    return head


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
    assert revision == script_head(settings)

    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            recorded = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()

    assert "alembic_version" in tables
    assert recorded == revision
    assert set(Base.metadata.tables) <= tables


def test_downgrade_and_upgrade_again_on_a_disposable_database(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "cycle.db")
    config = alembic_config(settings)

    command.upgrade(config, "head")
    assert current_revision(settings) == script_head(settings)

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
    assert current_revision(settings) == script_head(settings)


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


#: The last numbered revision.  Every later revision chains linearly from it.
LAST_NUMBERED_REVISION = "0013"


def script_directory(tmp_path: Path) -> ScriptDirectory:
    return ScriptDirectory.from_config(alembic_config(make_settings(tmp_path, "script.db")))


def declared_revisions(directory: ScriptDirectory) -> list[str]:
    """Read every ``revision = ...`` assignment in the versions folder."""
    revisions: list[str] = []
    for path in sorted(Path(directory.versions).glob("*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            target = node.target if isinstance(node, ast.AnnAssign) else None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "revision":
                assert node.value is not None, path.name
                revisions.append(ast.literal_eval(node.value))
    return revisions


def test_migrations_have_a_single_head(tmp_path: Path) -> None:
    heads = script_directory(tmp_path).get_heads()
    assert len(heads) == 1, f"migration heads: {sorted(heads)}"


def test_migration_revision_ids_are_unique(tmp_path: Path) -> None:
    directory = script_directory(tmp_path)
    revisions = declared_revisions(directory)
    assert len(revisions) == len(list(Path(directory.versions).glob("*.py")))
    duplicates = sorted({revision for revision in revisions if revisions.count(revision) > 1})
    assert not duplicates, f"duplicate revision ids: {duplicates}"


def test_migrations_form_a_linear_chain_from_0013(tmp_path: Path) -> None:
    directory = script_directory(tmp_path)
    chain = []
    revision = directory.get_revision(directory.get_current_head())
    while revision is not None:
        assert not revision.is_merge_point, f"{revision.revision} merges branches"
        assert isinstance(revision.down_revision, (str, type(None))), revision.revision
        chain.append(revision.revision)
        revision = directory.get_revision(revision.down_revision) if revision.down_revision else None
    chain.reverse()

    # Every revision lies on the one chain, which passes through 0013.
    assert sorted(chain) == sorted(declared_revisions(directory))
    assert LAST_NUMBERED_REVISION in chain
    numbered = chain[: chain.index(LAST_NUMBERED_REVISION) + 1]
    assert numbered == [f"{number:04d}" for number in range(1, len(numbered) + 1)]
    for later in chain[len(numbered) :]:
        assert not later.isdigit(), f"revision {later} after 0013 must use a non-numeric id"
