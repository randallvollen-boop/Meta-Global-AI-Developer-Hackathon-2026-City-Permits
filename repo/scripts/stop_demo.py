#!/usr/bin/env python3
"""Stop only the ACME City server recorded by this repository."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from demo_process import (
    DEFAULT_RECORD,
    pid_is_alive,
    read_record,
    record_matches_process,
    terminate_owned_process,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--timeout", type=float, default=8.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.record.exists():
        print("no demo process record exists")
        return 0
    try:
        record = read_record(args.record)
        pid = int(record["pid"])
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"refusing to stop: invalid process record ({error})", file=sys.stderr)
        return 2

    if not pid_is_alive(pid):
        args.record.unlink(missing_ok=True)
        print(f"removed stale demo process record for PID {pid}")
        return 0
    if not record_matches_process(record):
        print("refusing to signal a process that does not match the demo record", file=sys.stderr)
        return 3
    if not terminate_owned_process(record, timeout=args.timeout):
        print(f"demo process {pid} did not stop", file=sys.stderr)
        return 4

    args.record.unlink(missing_ok=True)
    print(f"stopped ACME City demo process {pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
