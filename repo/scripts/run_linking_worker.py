"""Process the queued registry linking work once.

The script is the local worker of the registry automation.  It runs one
bounded pass and prints what it did; it never starts a server and it never
stays resident.  The worker uses the built in deterministic logic of the
City, so it sends no request to any model provider.

The deployment decides whether the worker runs at all: a deployment whose
registry automation is paused has nothing to do, and the script says so
instead of working quietly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:  # pragma: no cover - script bootstrap
    sys.path.insert(0, str(REPO_ROOT / "src"))

from acme_city.agents.linking import MAX_JOBS_PER_CYCLE, run_once  # noqa: E402
from acme_city.core.clock import utc_now  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402
from acme_city.persistence.session import SessionFactory, transaction  # noqa: E402


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line of the worker."""
    parser = argparse.ArgumentParser(
        description="Process the queued registry linking work once."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one pass and exit (the only supported mode)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=MAX_JOBS_PER_CYCLE,
        help="the maximum number of jobs handled in one pass",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="the database URL; the configured database is used by default",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run one pass of the linking worker and report what it did."""
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
    if settings.registry_automation_mode == "paused":
        print(
            json.dumps(
                {
                    "code": "automation_paused",
                    "message": (
                        "the registry automation of this deployment is paused, "
                        "so no linking work is processed"
                    ),
                    "processed": 0,
                }
            )
        )
        return 0

    started_at = utc_now()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            report = run_once(
                session,
                now=started_at,
                limit=arguments.limit,
                started_at=started_at,
            )
            payload = {
                "recovered": report.recovered,
                "reopened": report.reopened,
                "processed": [
                    {
                        "job_id": outcome.job_id,
                        "status": outcome.status,
                        "decision": outcome.decision,
                        "entity_id": outcome.entity_id,
                        "score": outcome.score,
                        "attempts": outcome.attempts,
                        "note": outcome.note,
                    }
                    for outcome in report.processed
                ],
            }
    finally:
        factory.dispose()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
