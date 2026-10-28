#!/usr/bin/env python3
"""Add the Cedarline steward demonstration to a fictional demo database.

This is a prepare mode.  It is never part of a reset, an acceptance run or a
D-scenario fixture.  It proposes (never decides) the candidate links of three
Cedarline source records so the Data issues queue holds a story: Cedarline
Coffee Roasters LLC (alias Cedar Line Coffee Roasters) against Cedarline
Coffee Works LLC, a different license number.

Usage:

    uv run python scripts/load_steward_demo.py --database sqlite:///var/demo.db \
        --confirm-fictional-demo
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from acme_city.core.config import Settings
from acme_city.fixtures.reset import ENVIRONMENT_ID
from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import get_session_factory, initialize_database, transaction

CONFIRMATION_FLAG = "--confirm-fictional-demo"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=None)
    parser.add_argument(CONFIRMATION_FLAG, action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.confirm_fictional_demo:
        print(f"refusing to load: pass {CONFIRMATION_FLAG}", file=sys.stderr)
        return 2
    settings = Settings.load()
    if args.database:
        settings = settings.model_copy(update={"database_url": args.database})
    initialize_database(settings)
    factory = get_session_factory(settings.database_url)
    try:
        with transaction(factory) as session:
            marker = session.execute(
                select(DemoEnvironment).where(DemoEnvironment.environment_id == ENVIRONMENT_ID)
            ).scalar_one_or_none()
            if marker is None or not marker.fictional_demo:
                print("refusing to load: the target is not a marked fictional demo", file=sys.stderr)
                return 3
            proposals = seed_cedarline(session)
    finally:
        factory.dispose()
    print(f"proposed {len(proposals)} Cedarline candidate links; nothing is decided")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
