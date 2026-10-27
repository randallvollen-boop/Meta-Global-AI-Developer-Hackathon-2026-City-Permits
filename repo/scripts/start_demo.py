#!/usr/bin/env python3
"""Start the owned ACME City demonstration server on loopback."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from demo_process import (
    APP_TARGET,
    DEFAULT_LOG,
    DEFAULT_RECORD,
    LOOPBACK_HOSTS,
    REPO_ROOT,
    atomic_write_json,
    pid_is_alive,
    port_is_available,
    process_start_ticks,
    read_record,
    record_matches_process,
    terminate_owned_process,
    wait_for_health,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8266)
    parser.add_argument("--database", default=None, help="Optional SQLite URL for the demo process")
    parser.add_argument("--record", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--startup-timeout", type=float, default=20.0)
    return parser.parse_args(argv)


def _clear_stale_record(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        record = read_record(path)
        pid = int(record["pid"])
    except (OSError, ValueError, TypeError, KeyError):
        print(f"refusing to replace invalid process record: {path}", file=sys.stderr)
        return False
    if pid_is_alive(pid):
        if record_matches_process(record):
            print(f"demo server is already running with PID {pid}", file=sys.stderr)
        else:
            print("refusing to replace a record whose PID belongs to another process", file=sys.stderr)
        return False
    path.unlink()
    return True


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.host not in LOOPBACK_HOSTS:
        print("refusing to bind outside loopback", file=sys.stderr)
        return 2
    if not 1 <= args.port <= 65535:
        print("port must be between 1 and 65535", file=sys.stderr)
        return 2
    if not _clear_stale_record(args.record):
        return 3
    if not port_is_available(args.host, args.port):
        print(f"refusing to start: {args.host}:{args.port} is occupied", file=sys.stderr)
        return 4

    args.log.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    if args.database:
        environment["ACME_DATABASE_URL"] = args.database
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        APP_TARGET,
        "--factory",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--no-access-log",
    ]
    with args.log.open("ab", buffering=0) as log_handle:
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )

    ticks = None
    for _ in range(20):
        ticks = process_start_ticks(process.pid)
        if ticks is not None:
            break
        time.sleep(0.05)
    if ticks is None:
        process.terminate()
        print("demo server exited before its identity could be recorded", file=sys.stderr)
        return 5

    record = {
        "pid": process.pid,
        "process_start_ticks": ticks,
        "host": args.host,
        "port": args.port,
        "repository": str(REPO_ROOT),
        "database": args.database or environment.get("ACME_DATABASE_URL", "sqlite:///var/acme_city.db"),
        "app_target": APP_TARGET,
        "command": command,
        "started_at": datetime.now(UTC).isoformat(),
        "log": str(args.log.resolve()),
    }
    atomic_write_json(args.record, record)

    if not wait_for_health(args.host, args.port, timeout=args.startup_timeout):
        terminate_owned_process(record, timeout=2.0)
        args.record.unlink(missing_ok=True)
        print(f"demo server failed its health check; inspect {args.log}", file=sys.stderr)
        return 6

    print(f"ACME City demo: http://{args.host}:{args.port}")
    print(f"process record: {args.record}")
    print(f"server log: {args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
