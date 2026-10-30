#!/usr/bin/env python3
"""Reset and prepare one clearly labelled ACME City user-test state."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from demo_process import DEFAULT_RECORD, REPO_ROOT, atomic_write_json, pid_is_alive, read_record

DEFAULT_DATABASE = f"sqlite:///{(REPO_ROOT / 'var' / 'acme_city.db').resolve()}"
STATE_FILE = REPO_ROOT / "var" / "user-test-state.json"
RESET = REPO_ROOT / "scripts" / "reset_demo.py"
START = REPO_ROOT / "scripts" / "start_demo.py"
STOP = REPO_ROOT / "scripts" / "stop_demo.py"
WALKTHROUGH = REPO_ROOT / "scripts" / "demo_walkthrough.py"
MODE_LABELS = {
    "fresh": "Fresh fictional fixtures; D01 awaits stewardship and review.",
    "ready-for-review": "D01 has replay-labelled Muse evidence and approved identity links.",
    "completed-reference": "D01 has a replay-labelled reference chain and an issued simulated permit.",
    "steward-demo": (
        "Fresh fixtures plus three proposed Cedarline links in Data issues: Cedarline "
        "Coffee Roasters LLC against Cedarline Coffee Works LLC. Nothing is decided."
    ),
    "steward-automation": (
        "Fresh fixtures plus three proposed Cedarline links and one link the automatic "
        "linking applied. The steward may keep that link or undo it with a reason."
    ),
    "demo-synthetic": (
        "Fresh fixtures plus a flagged synthetic year of permit history for the City view "
        "and the public community view."
    ),
}
LOAD_SYNTHETIC = REPO_ROOT / "scripts" / "load_synthetic_year.py"
LOAD_STEWARD_DEMO = REPO_ROOT / "scripts" / "load_steward_demo.py"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=tuple(MODE_LABELS), default="fresh")
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8266)
    parser.add_argument("--record", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--state-file", type=Path, default=STATE_FILE)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=REPO_ROOT / "evidence" / "runs" / "user-test-prep",
    )
    parser.add_argument("--synthetic-seed", type=int, default=None)
    parser.add_argument("--synthetic-count", type=int, default=None)
    parser.add_argument(
        "--live-muse",
        action="store_true",
        help="Use one bounded live extraction instead of the default labelled replay.",
    )
    return parser.parse_args(argv)


def run_command(command: list[str], *, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise RuntimeError(f"command failed with exit {result.returncode}: {detail}")
    return result


def assert_server_stopped(record_path: Path) -> None:
    if not record_path.exists():
        return
    try:
        record = read_record(record_path)
        pid = int(record["pid"])
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise RuntimeError(f"invalid demo process record must be inspected: {record_path}") from error
    if pid_is_alive(pid):
        raise RuntimeError("stop the owned demo server before resetting its database")
    record_path.unlink()


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    if args.live_muse and args.mode in {"fresh", "demo-synthetic", "steward-demo", "steward-automation"}:
        raise RuntimeError("--live-muse requires ready-for-review or completed-reference mode")
    assert_server_stopped(args.record)
    environment = os.environ.copy()
    environment["ACME_DATABASE_URL"] = args.database

    run_command(
        [
            sys.executable,
            str(RESET),
            "--database",
            args.database,
            "--confirm-fictional-demo",
        ],
        environment=environment,
    )

    if args.mode == "demo-synthetic":
        command = [
            sys.executable,
            str(LOAD_SYNTHETIC),
            "--database",
            args.database,
            "--confirm-fictional-demo",
        ]
        if args.synthetic_seed is not None:
            command += ["--seed", str(args.synthetic_seed)]
        if args.synthetic_count is not None:
            command += ["--count", str(args.synthetic_count)]
        run_command(command, environment=environment)

    if args.mode == "steward-demo":
        run_command(
            [
                sys.executable,
                str(LOAD_STEWARD_DEMO),
                "--database",
                args.database,
                "--confirm-fictional-demo",
            ],
            environment=environment,
        )

    if args.mode == "steward-automation":
        run_command(
            [
                sys.executable,
                str(LOAD_STEWARD_DEMO),
                "--database",
                args.database,
                "--confirm-fictional-demo",
                "--automation",
            ],
            environment=environment,
        )

    walkthrough_path = None
    started = False
    try:
        if args.mode not in {"fresh", "demo-synthetic", "steward-demo", "steward-automation"}:
            run_command(
                [
                    sys.executable,
                    str(START),
                    "--host",
                    args.host,
                    "--port",
                    str(args.port),
                    "--database",
                    args.database,
                    "--record",
                    str(args.record),
                ],
                environment=environment,
            )
            started = True
            stop_after = "ready-for-review" if args.mode == "ready-for-review" else "issued"
            provider_mode = "live" if args.live_muse else "replay"
            run_command(
                [
                    sys.executable,
                    str(WALKTHROUGH),
                    "--base-url",
                    f"http://{args.host}:{args.port}",
                    "--mode",
                    provider_mode,
                    "--stop-after",
                    stop_after,
                    "--evidence-dir",
                    str(args.evidence_dir),
                ],
                environment=environment,
            )
            walkthrough_path = str((args.evidence_dir / "demo-walkthrough.json").resolve())
    finally:
        if started:
            run_command(
                [sys.executable, str(STOP), "--record", str(args.record)],
                environment=environment,
            )

    state = {
        "kind": "acme_city_user_test_state",
        "mode": args.mode,
        "label": MODE_LABELS[args.mode],
        "database": args.database,
        "model_mode": "live" if args.live_muse else ("replay" if args.mode not in {"fresh", "demo-synthetic", "steward-demo", "steward-automation"} else "none"),
        "walkthrough_evidence": walkthrough_path,
        "prepared_at": datetime.now(UTC).isoformat(),
        "server_running": False,
    }
    atomic_write_json(args.state_file, state)
    return state


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        state = prepare(args)
    except (RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(f"user-test preparation failed: {error}", file=sys.stderr)
        return 1
    print(f"prepared mode: {state['mode']}")
    print(state["label"])
    print(f"state record: {args.state_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
