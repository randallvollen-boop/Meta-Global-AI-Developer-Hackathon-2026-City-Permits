#!/usr/bin/env python3
"""Post simulated incoming permits to a running ACME City demo.

The records are fictional and deterministic.  The script signs in as a
persona through the server-held session API (Data Steward by default, which
holds the staging grant), then posts each record to the intake API, which
stages it, creates the Permitting application and runs the triage pipeline.

Usage:

    uv run python scripts/simulate_intake.py --scenario fence-conforming-rear
    uv run python scripts/simulate_intake.py --scenario mixed --count 6 \
        --base-url http://127.0.0.1:8266
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from acme_city.portal_intake.scenarios import SCENARIO_NAMES, build_scenario  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, choices=SCENARIO_NAMES)
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--base-url", default="http://127.0.0.1:8266")
    parser.add_argument("--actor", default="persona_data_steward")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    records = build_scenario(args.scenario)
    if args.count is not None:
        records = records[: args.count]
    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        selected = client.post("/api/session/select", json={"actor_id": args.actor})
        selected.raise_for_status()
        for record in records:
            response = client.post(
                "/api/intake/records", json=record.model_dump(mode="json")
            )
            response.raise_for_status()
            print(json.dumps(response.json(), sort_keys=True))
    print(f"submitted {len(records)} record(s) for scenario {args.scenario!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
