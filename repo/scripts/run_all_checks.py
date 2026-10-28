#!/usr/bin/env python3
"""Run every local ACME City verification gate and preserve child exit codes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = REPO_ROOT / "config" / "check_inventory.json"


def pytest_only_paths() -> list[str]:
    """Return the test directories the deterministic acceptance run does not execute.

    The deterministic-acceptance step runs every non-browser family of the
    check inventory with its own evidence, so the plain pytest step runs only
    what that step leaves out: the browser families and any test directory no
    family declares.  Every collected test still runs exactly once.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from run_acceptance import load_inventory, selected_families
    finally:
        sys.path.pop(0)
    covered = {
        Path(path).as_posix().rstrip("/")
        for family in selected_families(load_inventory(INVENTORY_PATH), mode="deterministic")
        for path in family.get("paths") or []
    }
    return sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "tests").iterdir()
        if path.is_dir()
        and path.name != "__pycache__"
        and path.relative_to(REPO_ROOT).as_posix() not in covered
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=REPO_ROOT / "evidence" / "runs" / "final",
    )
    return parser.parse_args(argv)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_step(
    *,
    name: str,
    command: list[str],
    logs: Path,
    environment: dict[str, str],
    stdout_file: Path | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    duration = round(time.monotonic() - started, 3)
    log_path = logs / f"{name}.log"
    log_path.write_text(
        f"$ {' '.join(command)}\n\n[stdout]\n{result.stdout}\n[stderr]\n{result.stderr}",
        encoding="utf-8",
    )
    if stdout_file is not None:
        stdout_file.parent.mkdir(parents=True, exist_ok=True)
        stdout_file.write_text(result.stdout, encoding="utf-8")
    return {
        "name": name,
        "command": command,
        "exit_code": result.returncode,
        "duration_seconds": duration,
        "log": str(log_path.relative_to(logs.parent)),
        "log_sha256": file_hash(log_path),
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    evidence_dir = args.evidence_dir.resolve()
    logs = evidence_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    collection = REPO_ROOT / "var" / "final-collection.txt"
    deterministic = evidence_dir / "deterministic"
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "0"
    schema_database = evidence_dir / f"schema-check-{os.getpid()}.db"
    schema_environment = {
        **environment,
        "ACME_DATABASE_URL": f"sqlite:///{schema_database}",
    }

    commands: list[tuple[str, list[str], Path | None]] = [
        (
            "compile",
            [sys.executable, "-m", "compileall", "-q", "src", "scripts", "tests"],
            None,
        ),
        (
            "requirement-coverage",
            [sys.executable, "scripts/check_requirement_coverage.py"],
            None,
        ),
        (
            "collect",
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            collection,
        ),
        (
            "collection-contract",
            [sys.executable, "scripts/check_test_collection.py", str(collection)],
            None,
        ),
        ("pytest", [sys.executable, "-m", "pytest", "-q", *pytest_only_paths()], None),
        (
            "alembic-upgrade",
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            None,
        ),
        ("alembic", [sys.executable, "-m", "alembic", "check"], None),
        (
            "deterministic-acceptance",
            [
                sys.executable,
                "scripts/run_acceptance.py",
                "--deterministic",
                "--evidence-dir",
                str(deterministic),
            ],
            None,
        ),
        (
            "evidence-verification",
            [sys.executable, "scripts/verify_evidence.py", str(deterministic)],
            None,
        ),
        (
            "publishable-tree",
            [sys.executable, "scripts/scan_publishable_tree.py"],
            None,
        ),
    ]

    started_at = datetime.now(UTC)
    results: list[dict[str, Any]] = []
    for name, command, stdout_file in commands:
        print(f"[{name}] {' '.join(command)}", flush=True)
        step_environment = (
            schema_environment if name in {"alembic-upgrade", "alembic"} else environment
        )
        result = run_step(
            name=name,
            command=command,
            logs=logs,
            environment=step_environment,
            stdout_file=stdout_file,
        )
        results.append(result)
        print(f"[{name}] exit {result['exit_code']} in {result['duration_seconds']}s", flush=True)

    failed = [result for result in results if result["exit_code"] != 0]
    summary = {
        "kind": "acme_city_all_checks",
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "status": "passed" if not failed else "failed",
        "steps": results,
        "failed_steps": [result["name"] for result in failed],
    }
    summary_path = evidence_dir / "run-all-summary.json"
    atomic_json(summary_path, summary)
    print(f"summary: {summary_path}")
    if failed:
        print(
            "failed gates: " + ", ".join(result["name"] for result in failed),
            file=sys.stderr,
        )
        return 1
    print(f"all {len(results)} local verification gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
