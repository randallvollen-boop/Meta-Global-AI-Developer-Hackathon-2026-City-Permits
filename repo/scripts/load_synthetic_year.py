#!/usr/bin/env python3
"""Load the seeded synthetic permit history into a fictional demo database.

The default reset never loads it.  Run this after a reset (the demo-synthetic
prepare mode does both).  Every row it writes is flagged synthetic; the loader
runs no agent, calls no provider and writes no audit event.

Usage:

    uv run python scripts/load_synthetic_year.py --database sqlite:///var/demo.db \
        --seed 20261028 --count 600 --confirm-fictional-demo
"""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import select

from acme_city.core.config import Settings
from acme_city.fixtures.reset import ENVIRONMENT_ID
from acme_city.fixtures.synthetic import load_synthetic_year
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import get_session_factory, initialize_database, transaction
from acme_city.portal_intake.scenarios import load_distributions

CONFIRMATION_FLAG = "--confirm-fictional-demo"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    limits = load_distributions()["limits"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=None)
    parser.add_argument("--seed", type=int, default=int(limits["default_seed"]))
    parser.add_argument("--count", type=int, default=int(limits["default_count"]))
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
            result = load_synthetic_year(session, seed=args.seed, count=args.count)
    except (ValueError, RuntimeError) as error:
        print(f"synthetic load failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
