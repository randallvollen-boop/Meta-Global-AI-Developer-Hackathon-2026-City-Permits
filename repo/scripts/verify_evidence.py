#!/usr/bin/env python3
"""Verify the manifest of an acceptance run.

The verifier checks the shape of the manifest, the counts of the checks, the
status of every check, the versions and the hashes it names, the hashes of
the artifacts on disk, and that no secret, cookie or authorization header
reached the file.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from acme_city.evidence.manifest import (  # noqa: E402
    MANIFEST_NAME,
    assert_no_secrets,
    sha256_file,
)
from acme_city.evidence.schemas import (  # noqa: E402
    CHECK_KIND_ACCEPTANCE,
    CHECK_KIND_SCENARIO,
    CHECK_KIND_SUPPLEMENTARY,
    CHECK_STATUSES,
    METRIC_GROUPS,
)

EXPECTED_CHECKS = {
    CHECK_KIND_ACCEPTANCE: 20,
    CHECK_KIND_SUPPLEMENTARY: 8,
    CHECK_KIND_SCENARIO: 11,
}

REQUIRED_KEYS = (
    "run_id",
    "mode",
    "started_at",
    "finished_at",
    "build_hash",
    "tree_hash",
    "fixture_version",
    "database_schema_revision",
    "source_snapshots",
    "model",
    "prompt_versions",
    "schema_versions",
    "rule_versions",
    "actors",
    "checks",
    "artifacts",
    "metrics",
    "metric_groups",
    "failures",
    "commands",
)

HASH = re.compile(r"^[0-9a-f]{64}$")


def known_requirements() -> set[str]:
    """Return the requirement identifiers of the committed contract."""
    contract = REPO_ROOT / "config" / "requirements.json"
    if not contract.is_file():
        return set()
    payload = json.loads(contract.read_text(encoding="utf-8"))
    return {entry["requirement_id"] for entry in payload.get("requirements") or []}


def verify(directory: Path) -> list[str]:
    """Return the problems of the manifest in an evidence directory."""
    problems: list[str] = []
    path = directory / MANIFEST_NAME
    if not path.is_file():
        return [f"the evidence directory holds no {MANIFEST_NAME}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"the manifest is not valid JSON: {exc}"]
    if not isinstance(payload, dict):
        return ["the manifest must be a JSON object"]

    for key in REQUIRED_KEYS:
        if key not in payload:
            problems.append(f"the manifest has no {key}")
    if problems:
        return problems

    try:
        assert_no_secrets(payload)
    except Exception as exc:  # noqa: BLE001 - the message names the offending path
        problems.append(f"the manifest carries a credential: {exc}")

    for key in ("build_hash", "tree_hash"):
        if not HASH.match(str(payload[key])):
            problems.append(f"the {key} is not a SHA-256 hash")
    for key in ("fixture_version", "database_schema_revision"):
        if not str(payload[key]).strip():
            problems.append(f"the manifest names no {key}")

    checks = payload["checks"]
    counts: dict[str, int] = {kind: 0 for kind in EXPECTED_CHECKS}
    requirement_ids = known_requirements()
    artifact_hashes = {
        artifact.get("sha256") for artifact in payload["artifacts"] if artifact.get("sha256")
    }
    for check in checks:
        kind = check.get("kind")
        if kind in counts:
            counts[kind] += 1
        else:
            problems.append(f"the check {check.get('check_id')} has the unknown kind {kind}")
        status = check.get("status")
        if status not in CHECK_STATUSES:
            problems.append(f"the check {check.get('check_id')} has the status {status!r}")
        if status == "passed" and check.get("failure"):
            problems.append(f"the passed check {check.get('check_id')} carries a failure")
        if status in {"failed", "blocked"} and not check.get("failure"):
            problems.append(f"the {status} check {check.get('check_id')} carries no reason")
        if not check.get("expected"):
            problems.append(f"the check {check.get('check_id')} names no expectation")
        if not check.get("observed"):
            problems.append(f"the check {check.get('check_id')} names no observation")
        if not check.get("requirement_ids") and kind != CHECK_KIND_SCENARIO:
            problems.append(f"the check {check.get('check_id')} names no requirement")
        for requirement_id in check.get("requirement_ids") or []:
            if requirement_ids and requirement_id not in requirement_ids:
                problems.append(
                    f"the check {check.get('check_id')} names the unknown requirement "
                    f"{requirement_id}"
                )
        node_ids = set(check.get("node_ids") or [])
        for reference in check.get("evidence_refs") or []:
            if not str(reference).strip():
                problems.append(f"the check {check.get('check_id')} carries an empty reference")
                continue
            if HASH.match(str(reference)):
                if reference not in artifact_hashes:
                    problems.append(
                        f"the check {check.get('check_id')} refers to the unknown artifact "
                        f"hash {reference}"
                    )
                continue
            if reference in node_ids:
                continue
            if "::" in str(reference):
                problems.append(
                    f"the check {check.get('check_id')} refers to the unknown node {reference}"
                )
    for kind, expected in EXPECTED_CHECKS.items():
        if counts.get(kind) != expected:
            problems.append(
                f"the manifest holds {counts.get(kind, 0)} {kind} checks, {expected} are required"
            )

    for artifact in payload["artifacts"]:
        name = artifact.get("name", "")
        digest = artifact.get("sha256", "")
        if not HASH.match(str(digest)):
            problems.append(f"the artifact {name} has no valid SHA-256 hash")
        target = directory / "artifacts" / name
        if not target.is_file():
            problems.append(f"the artifact {name} is missing from the evidence directory")
            continue
        if sha256_file(target) != digest:
            problems.append(f"the artifact {name} does not match its recorded hash")

    for command in payload["commands"]:
        if "exit_code" not in command:
            problems.append(f"the command {command.get('command')} records no exit code")

    groups = payload["metric_groups"]
    if set(groups) != set(METRIC_GROUPS):
        problems.append(f"the manifest names the metric groups {sorted(groups)}")
    for group, metrics in groups.items():
        for metric in metrics:
            if metric.get("group") != group:
                problems.append(f"the metric {metric.get('label')} sits in the wrong group")
            if not metric.get("denominator"):
                problems.append(f"the metric {metric.get('label')} names no denominator")
            if group == "baseline_synthetic" and not metric.get("limitation"):
                problems.append(
                    f"the synthetic metric {metric.get('label')} carries no limitation"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_dir", type=Path, help="the evidence directory")
    args = parser.parse_args(argv)

    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    lock_handle = (args.evidence_dir / ".run.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_handle.close()
        print("evidence verification refused: the run is still being written", file=sys.stderr)
        return 2

    problems = verify(args.evidence_dir)
    if problems:
        print("evidence verification FAILED", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    payload = json.loads((args.evidence_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    print("evidence verification OK")
    print(f"  manifest: {args.evidence_dir / MANIFEST_NAME}")
    print(f"  run: {payload['run_id']} ({payload['mode']})")
    print(f"  fixture: {payload['fixture_version']}")
    print(f"  schema revision: {payload['database_schema_revision']}")
    counts: dict[str, int] = {}
    for check in payload["checks"]:
        counts[check["kind"]] = counts.get(check["kind"], 0) + 1
    for kind, count in sorted(counts.items()):
        print(f"  {kind} checks: {count}")
    status_counts = payload.get("status_counts") or {}
    print(
        "  status: "
        + " ".join(f"{status}={status_counts.get(status, 0)}" for status in CHECK_STATUSES)
    )
    print(f"  artifacts: {len(payload['artifacts'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
