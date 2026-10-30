#!/usr/bin/env python3
"""Reset the fictional ACME City demonstration database.

The reset is destructive.  It accepts only a SQLite database that the tool
itself marked as the fictional demonstration environment, and it requires the
exact confirmation phrase.  Any other target is refused.

Usage:

    uv run python scripts/reset_demo.py --database sqlite:///var/reset-test.db \
        --confirm-fictional-demo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# This script can be called by an installed virtual environment whose editable
# package points at another checkout.  Always reset with the source adjacent to
# this script, even when the caller deliberately supplies a minimal environment.
REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from sqlalchemy import inspect, select
from sqlalchemy.engine import make_url

from acme_city.core.config import Settings
from acme_city.core.errors import AcmeError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_assist_demo import seed_steward_assistant_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    current_revision,
    get_session_factory,
    initialize_database,
    transaction,
)

CONFIRMATION_FLAG = "--confirm-fictional-demo"


def sqlite_path(database_url: str) -> Path | None:
    """Return the file path of a SQLite URL, or ``None`` for another engine.

    The path is resolved with the same rules SQLAlchemy uses, so
    ``sqlite:///var/demo.db`` is the relative path ``var/demo.db`` and
    ``sqlite:////var/demo.db`` is the absolute path ``/var/demo.db``.
    """
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return None
    database = url.database
    if not database or database == ":memory:":
        return None
    return Path(database)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=None,
        help="SQLite database URL to reset. Defaults to the configured ACME_DATABASE_URL.",
    )
    parser.add_argument(
        CONFIRMATION_FLAG,
        action="store_true",
        help="Required confirmation that the target is the disposable fictional demo database.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root that holds the configuration and fixture documents.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.confirm_fictional_demo:
        print(
            f"refusing to reset: pass {CONFIRMATION_FLAG} to confirm the fictional demo target",
            file=sys.stderr,
        )
        return 2

    settings = Settings.load()
    if args.database:
        settings = settings.model_copy(update={"database_url": args.database})

    target = sqlite_path(settings.database_url)
    if target is None:
        print(
            "refusing to reset: only a SQLite demonstration database may be reset",
            file=sys.stderr,
        )
        return 2

    root = Path(args.root) if args.root else None
    bundle = FixtureBundle.load(root)
    confirmation = str(bundle.demo.reset.get("confirmation_phrase", CONFIRMATION_FLAG))

    existed = target.exists()
    if existed:
        probe = get_session_factory(settings.database_url)
        table_names = set(inspect(probe.engine).get_table_names())
        probe.dispose()
        if not table_names or (
            table_names == {"alembic_version"} and current_revision(settings) is None
        ):
            existed = False
        elif "demo_environment" not in table_names:
            print(
                "refusing to reset: the existing database is not an empty or marked demo",
                file=sys.stderr,
            )
            return 3

    if not existed:
        target.parent.mkdir(parents=True, exist_ok=True)
        initialize_database(settings)
        factory = get_session_factory(settings.database_url)
        with transaction(factory) as session:
            session.add(
                DemoEnvironment(
                    id="demo_environment_local",
                    environment_id=ENVIRONMENT_ID,
                    fictional_demo=True,
                    fixture_version=bundle.fixture_version,
                    label="local fictional demonstration",
                )
            )
    else:
        factory = get_session_factory(settings.database_url)
        with transaction(factory) as session:
            marker = session.execute(
                select(DemoEnvironment).where(
                    DemoEnvironment.environment_id == ENVIRONMENT_ID
                )
            ).scalar_one_or_none()
            if marker is None or not marker.fictional_demo:
                print(
                    "refusing to reset: the target database is not marked fictional_demo=true",
                    file=sys.stderr,
                )
                return 3
        # A marked demo from an older build is upgraded only after the marker check.
        factory.dispose()
        initialize_database(settings)

    factory = get_session_factory(settings.database_url)
    with transaction(factory) as session:
        result = reset_demo(session, bundle, confirmation=confirmation)
        # The demonstration of the steward assistant: three tasks of the
        # queue of the Data Steward, one for each certainty the assistant can
        # reach.  Nothing is decided here.
        demo_counts = seed_steward_assistant_demo(session, bundle)

    print(f"fixture version: {result.fixture_version}")
    print(f"database target: sqlite ({target.name})")
    for name in sorted(result.counts):
        print(f"  {name}: {result.counts[name]}")
    for name in sorted(demo_counts):
        print(f"  {name}: {demo_counts[name]}")
    print(f"total seeded rows: {result.total}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcmeError as error:
        print(f"reset failed: {error.message}", file=sys.stderr)
        raise SystemExit(1) from error
