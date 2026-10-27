"""Send the pending source commands and deliver the pending publications.

The script is the local outbox worker of the demonstration.  It runs once and
prints what it did; it never starts a server and it never stays resident.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:  # pragma: no cover - script bootstrap
    sys.path.insert(0, str(REPO_ROOT / "src"))

from acme_city.changes.dispatcher import ChangeDispatcher  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402
from acme_city.persistence.session import SessionFactory, transaction  # noqa: E402


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line of the worker."""
    parser = argparse.ArgumentParser(
        description="Dispatch the pending source commands and outbox deliveries once."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one dispatch pass and exit (the only supported mode)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="the maximum number of commands and deliveries handled in one pass",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="the database URL; the configured database is used by default",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run one dispatch pass and report what it did."""
    arguments = parse_arguments(argv)
    if not arguments.once:
        print(
            json.dumps(
                {
                    "code": "unsupported_mode",
                    "message": "the worker runs once; pass --once",
                }
            )
        )
        return 2

    settings = Settings.load()
    if arguments.database:
        settings = settings.model_copy(update={"database_url": arguments.database})
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            summary = ChangeDispatcher(session).dispatch_pending(limit=arguments.limit)
            payload = summary.model_dump(mode="json")
    finally:
        factory.dispose()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
