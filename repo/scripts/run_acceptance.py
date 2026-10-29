#!/usr/bin/env python3
"""Run the acceptance checks and record the evidence of the run.

The runner reads the requirement-linked check inventory, runs every family of
tests as a child process, keeps the exit code of every child, turns the
collected outcomes into one result per acceptance, supplementary and scenario
check, and writes a manifest that names the build, the versions, the actors,
the expected and the observed outcomes and the hashes of the artifacts.

A check that needs a live provider run is blocked in the deterministic mode.
It is never reported as passed, and a skipped check is never reported as
passed either.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from acme_city.evidence.manifest import (  # noqa: E402
    EvidenceRecorder,
    build_hash,
    hash_tree,
    sha256_file,
)
from acme_city.evidence.schemas import (  # noqa: E402
    CHECK_KIND_ACCEPTANCE,
    CHECK_KIND_SCENARIO,
    CHECK_KIND_SUPPLEMENTARY,
    CHECK_STATUS_BLOCKED,
    CHECK_STATUS_FAILED,
    CHECK_STATUS_PASSED,
    CheckResult,
    MetricGroup,
)

DEFAULT_INVENTORY = REPO_ROOT / "config" / "check_inventory.json"
DEFAULT_EVIDENCE_DIR = REPO_ROOT / "evidence" / "runs" / "deterministic"
EVALUATOR_REPORT_ENV = "ACME_EVALUATOR_REPORT"
EVALUATOR_REPORT_DEFAULT = REPO_ROOT / "var" / "evaluator_outcomes.json"
TRUTH_PATH = REPO_ROOT / "fixtures" / "evaluator_truth.json"

#: The families the deterministic run executes.  The browser family needs a
#: running service and is part of the full run, not of the deterministic one.
BROWSER_FAMILY = "browser"
# Each family runs on every core; tests/conftest.py keeps each test's database separate.
PYTEST_WORKERS = ["-n", "auto"]


@dataclass
class FamilyResult:
    """What one child process did."""

    name: str
    paths: list[str]
    exit_code: int
    collected: int
    passed: int
    failed: int
    skipped: int
    duration_seconds: float
    outcomes: dict[str, str] = field(default_factory=dict)
    junit_path: Path | None = None
    collect_exit_code: int = 0
    nodes: list[str] = field(default_factory=list)


def load_inventory(path: Path) -> dict[str, Any]:
    """Return the requirement-linked check inventory."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"the check inventory is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"the check inventory is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("the check inventory must be a JSON object")
    return payload


def selected_families(inventory: dict[str, Any], *, mode: str) -> list[dict[str, Any]]:
    """Return the families the requested mode runs."""
    families = inventory.get("families") or {}
    chosen: list[dict[str, Any]] = []
    for name, definition in families.items():
        family_mode = str(definition.get("mode", "deterministic"))
        if mode == "deterministic" and family_mode == BROWSER_FAMILY:
            continue
        chosen.append({"name": name, **definition})
    return chosen


def collect_nodes(paths: list[str]) -> tuple[list[str], int]:
    """Return the node identifiers pytest collects for the given paths and its exit code."""
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q", *paths]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    nodes = [
        line.strip()
        for line in completed.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    ]
    return nodes, completed.returncode


def junit_key(nodeid: str) -> tuple[str, str]:
    """Return the class and the name that the JUnit report uses for a node."""
    parts = nodeid.split("::")
    module = parts[0].replace("/", ".").removesuffix(".py")
    return ".".join([module, *parts[1:-1]]), parts[-1]


def read_junit(path: Path, nodes: Iterable[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Return the outcome of every executed node and the reason of a skip."""
    lookup = {junit_key(node): node for node in nodes}
    outcomes: dict[str, str] = {}
    reasons: dict[str, str] = {}
    if not path.is_file():
        return outcomes, reasons
    tree = ElementTree.parse(path)
    for case in tree.iter("testcase"):
        key = (case.get("classname", ""), case.get("name", ""))
        nodeid = lookup.get(key)
        if nodeid is None:
            continue
        if case.find("failure") is not None or case.find("error") is not None:
            outcomes[nodeid] = "failed"
            continue
        skipped = case.find("skipped")
        if skipped is not None:
            outcomes[nodeid] = "skipped"
            reasons[nodeid] = (skipped.get("message") or "the test was skipped").strip()
            continue
        outcomes[nodeid] = "passed"
    return outcomes, reasons


def run_family(
    name: str,
    paths: list[str],
    artifacts: Path,
) -> FamilyResult:
    """Run one family of tests and keep the exit code of the child."""
    started = time.monotonic()
    nodes, collect_exit_code = collect_nodes(paths)
    junit_path = artifacts / f"{name}.junit.xml"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-o",
        "junit_family=xunit1",
        f"--junitxml={junit_path}",
        *PYTEST_WORKERS,
        *paths,
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    duration = time.monotonic() - started
    (artifacts / f"{name}.log").write_text(
        completed.stdout + completed.stderr, encoding="utf-8"
    )
    outcomes, reasons = read_junit(junit_path, nodes)
    passed = sum(1 for value in outcomes.values() if value == "passed")
    failed = sum(1 for value in outcomes.values() if value == "failed")
    skipped = sum(1 for value in outcomes.values() if value == "skipped")
    for nodeid, reason in reasons.items():
        outcomes[nodeid] = f"skipped: {reason}"
    return FamilyResult(
        name=name,
        paths=list(paths),
        exit_code=completed.returncode,
        collected=len(nodes),
        passed=passed,
        failed=failed,
        skipped=skipped,
        duration_seconds=duration,
        outcomes={node: value.split(":")[0] for node, value in outcomes.items()},
        junit_path=junit_path,
        collect_exit_code=collect_exit_code,
        nodes=list(nodes),
    )


def status_for(
    check: dict[str, Any],
    outcomes: dict[str, str],
    *,
    live_executed: bool,
    reasons: dict[str, str],
) -> tuple[str, str]:
    """Return the status of one check and the reason when it is not passed."""
    node_ids = list(check.get("node_ids") or [])
    if not node_ids:
        if check.get("pending"):
            return (
                CHECK_STATUS_BLOCKED,
                "the check has no collected node yet",
            )
        return CHECK_STATUS_FAILED, "the check has no executable node"
    # A deterministic failure is reported as a failure even on a check that
    # also needs live evidence; "blocked" never hides a failing node.
    missing = [nodeid for nodeid in node_ids if nodeid not in outcomes]
    if missing:
        return (
            CHECK_STATUS_FAILED,
            f"the collected node {missing[0]} did not run",
        )
    failed = [nodeid for nodeid in node_ids if outcomes[nodeid] == "failed"]
    if failed:
        return CHECK_STATUS_FAILED, f"the node {failed[0]} failed"
    if check.get("live_required") and not live_executed:
        return (
            CHECK_STATUS_BLOCKED,
            "the check needs a live provider run, which this run did not make",
        )
    skipped = [nodeid for nodeid in node_ids if outcomes[nodeid] == "skipped"]
    if skipped:
        reason = reasons.get(skipped[0], "the test was skipped")
        return (
            CHECK_STATUS_BLOCKED,
            f"the node {skipped[0]} was skipped: {reason}",
        )
    return CHECK_STATUS_PASSED, ""


def evaluator_report() -> dict[str, Any]:
    """Return the report of the evaluator run, when there is one."""
    path = Path(os.environ.get(EVALUATOR_REPORT_ENV, str(EVALUATOR_REPORT_DEFAULT)))
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def family_of_node(nodeid: str) -> str:
    """Return the family a collected node belongs to."""
    parts = nodeid.split("::")[0].split("/")
    if len(parts) < 2 or parts[0] != "tests":
        return "other"
    return parts[1]


def run_versions() -> dict[str, Any]:
    """Return the versions, the sources and the actors of the run.

    The manifest has to name what the run was made against: the source
    snapshots it read, the model and its prompt and schema versions, the
    rule versions it applied and the actors that acted.
    """
    from acme_city.muse.schemas import (
        EXTRACTION_PROMPT_VERSION,
        EXTRACTION_SCHEMA_VERSION,
        MATCH_PROMPT_VERSION,
        MATCH_SCHEMA_VERSION,
    )

    sources: dict[str, str] = {}
    for name in ("base_population.json", "source_variations.json"):
        path = REPO_ROOT / "fixtures" / name
        if path.is_file():
            sources[f"fixtures/{name}"] = sha256_file(path)

    rules_path = REPO_ROOT / "config" / "rules_and_fees.json"
    rule_versions: dict[str, str] = {}
    if rules_path.is_file():
        catalog = json.loads(rules_path.read_text(encoding="utf-8"))
        for rule in catalog.get("rules") or []:
            rule_versions[str(rule.get("rule_id"))] = str(rule.get("version"))
        for schedule in catalog.get("fee_schedules") or []:
            key = f"{schedule.get('fee_schedule_id')}:{schedule.get('version_label')}"
            rule_versions[key] = str(schedule.get("version_label"))

    actors_path = REPO_ROOT / "config" / "actors.json"
    actors: tuple[str, ...] = ()
    if actors_path.is_file():
        catalog = json.loads(actors_path.read_text(encoding="utf-8"))
        actors = tuple(
            str(persona.get("actor_id")) for persona in catalog.get("personas") or []
        )

    return {
        "source_snapshots": sources,
        "model": {
            "mode": "no_model_run",
            "provider": "meta",
            "model": "muse-spark-1.3",
            "note": "the deterministic run made no provider call",
        },
        "prompt_versions": {
            "extraction": EXTRACTION_PROMPT_VERSION,
            "match_proposal": MATCH_PROMPT_VERSION,
        },
        "schema_versions": {
            "extraction": EXTRACTION_SCHEMA_VERSION,
            "match_proposal": MATCH_SCHEMA_VERSION,
        },
        "rule_versions": rule_versions,
        "actors": actors,
    }


def observed_text(check: dict[str, Any], outcomes: dict[str, str]) -> str:
    """Return what the run saw for one check."""
    node_ids = list(check.get("node_ids") or [])
    if not node_ids:
        return "the check has no collected node yet"
    results = [outcomes.get(nodeid, "not run") for nodeid in node_ids]
    passed = sum(1 for value in results if value == "passed")
    failed = sum(1 for value in results if value == "failed")
    skipped = sum(1 for value in results if value == "skipped")
    return (
        f"{passed} of {len(node_ids)} collected nodes passed"
        + (f", {failed} failed" if failed else "")
        + (f", {skipped} skipped" if skipped else "")
    )


def build_checks(
    inventory: dict[str, Any],
    outcomes: dict[str, str],
    reasons: dict[str, str],
    report: dict[str, Any],
    *,
    live_executed: bool,
    artifact_hashes: dict[str, str] | None = None,
) -> list[CheckResult]:
    """Return one result per acceptance, supplementary and scenario check."""
    requirements = {
        entry["requirement_id"]: entry for entry in inventory.get("requirements") or []
    }
    by_check = {
        entry["check_id"]: entry for entry in inventory.get("checks") or []
    }
    scenarios = {
        str(entry.get("scenario_id")): entry
        for entry in report.get("scenarios") or []
    }
    results: list[CheckResult] = []
    for check_id, check in by_check.items():
        kind = str(check.get("kind", CHECK_KIND_ACCEPTANCE))
        status, failure = status_for(
            check, outcomes, live_executed=live_executed, reasons=reasons
        )
        requirement_ids = tuple(
            sorted(
                requirement_id
                for requirement_id, entry in requirements.items()
                if check_id in (entry.get("check_ids") or [])
            )
        )
        expected = str(check.get("expected", ""))
        observed = str(check.get("observed", ""))
        if kind == CHECK_KIND_SCENARIO and check_id in scenarios:
            scenario = scenarios[check_id]
            expected = str(scenario.get("expected", expected))
            observed = str(scenario.get("observed", observed))
        if not observed:
            observed = observed_text(check, outcomes)
        node_ids = tuple(check.get("node_ids") or [])
        evidence_refs = list(check.get("evidence_refs") or [])
        if artifact_hashes:
            for family in dict.fromkeys(family_of_node(node) for node in node_ids):
                digest = artifact_hashes.get(family)
                if digest and digest not in evidence_refs:
                    evidence_refs.append(digest)
        results.append(
            CheckResult(
                check_id=check_id,
                status=status,
                requirement_ids=requirement_ids,
                expected=expected,
                observed=observed,
                evidence_refs=tuple(evidence_refs),
                failure=failure or None,
                kind=kind,
                node_ids=node_ids,
                live_required=bool(check.get("live_required")),
            )
        )
    return results


def baseline_metrics() -> list[MetricGroup]:
    """Return the synthetic baseline of the fictional fixture."""
    if not TRUTH_PATH.is_file():
        return []
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    denominators = truth.get("truth_denominators") or {}
    limitation = (
        "a synthetic figure of the fictional demonstration fixture, not an observed "
        "result and not an estimate of real-world accuracy"
    )
    metrics: list[MetricGroup] = []
    labels = {
        "truth_expected_scenarios": "labeled controlled scenarios",
        "truth_expected_links": "labeled expected links",
        "truth_expected_false_links": "labeled false links",
        "truth_expected_unresolved": "labeled unresolved cases",
    }
    for key, label in labels.items():
        value = denominators.get(key)
        if value is None:
            continue
        metrics.append(
            MetricGroup(
                label=label,
                group="baseline_synthetic",
                numerator=float(value),
                denominator=float(value),
                unit="count",
                limitation=limitation,
                note="the evaluator truth of the demonstration fixture",
            )
        )
    return metrics


def observed_metrics(report: dict[str, Any]) -> list[MetricGroup]:
    """Return what this run observed in the model and the registry."""
    counts = report.get("counts") or {}
    metrics: list[MetricGroup] = []
    pairs = (
        ("expected_links_found", "labeled_expected_links", "expected links found"),
        ("false_links", "accepted_links", "false links"),
        ("unresolved_cases", "evaluated_cases", "unresolved cases"),
    )
    for numerator_key, denominator_key, label in pairs:
        numerator = counts.get(numerator_key)
        denominator = counts.get(denominator_key)
        if numerator is None or denominator is None:
            continue
        metrics.append(
            MetricGroup(
                label=label,
                group="observed_model_registry",
                numerator=float(numerator),
                denominator=float(denominator),
                unit="count",
                note="observed in this run against the labeled expectations",
                limitation="a demonstration check over a small fictional fixture",
            )
        )
    return metrics


def business_metrics(report: dict[str, Any]) -> list[MetricGroup]:
    """Return the business outcome of this run."""
    counts = report.get("counts") or {}
    metrics: list[MetricGroup] = []
    numerator = counts.get("scenarios_matched")
    denominator = counts.get("scenarios_evaluated")
    if numerator is not None and denominator is not None:
        metrics.append(
            MetricGroup(
                label="controlled scenarios with the expected outcome",
                group="business_outcome",
                numerator=float(numerator),
                denominator=float(denominator),
                unit="count",
                note="the workflow outcome the run observed for each controlled scenario",
                limitation="a demonstration check over a small fictional fixture",
            )
        )
    issued = counts.get("permits_issued")
    evaluated = counts.get("applications_evaluated")
    if issued is not None and evaluated is not None:
        metrics.append(
            MetricGroup(
                label="issued permits",
                group="business_outcome",
                numerator=float(issued),
                denominator=float(evaluated),
                unit="count",
                note="the simulated permits the run issued against the applications it evaluated",
            )
        )
    return metrics


def read_live_evidence(path: Path) -> tuple[bool, dict[str, Any], str]:
    """Validate the parent-owned walkthrough record without treating replay as live."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return False, {}, f"live walkthrough evidence could not be read: {error}"
    if not isinstance(payload, dict):
        return False, {}, "live walkthrough evidence is not a JSON object"
    run = payload.get("model_run")
    if not isinstance(run, dict):
        return False, payload, "live walkthrough evidence names no model run"
    if payload.get("mode") != "live" or run.get("mode") != "live":
        return False, payload, "replay or cached evidence cannot satisfy a live check"
    if payload.get("status") != "passed" or run.get("status") != "succeeded":
        response_id = run.get("response_id") or "unavailable"
        response_status = run.get("response_status") or "unavailable"
        return (
            False,
            payload,
            "the live model run did not succeed "
            f"(response_id={response_id}, response_status={response_status})",
        )
    if not run.get("response_id"):
        return False, payload, "the successful live run names no provider response"
    return True, payload, ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Return the parsed command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--deterministic",
        action="store_true",
        help="run the deterministic families only (the default)",
    )
    mode.add_argument(
        "--all",
        action="store_true",
        help="run every family the inventory declares, including the browser family",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=DEFAULT_EVIDENCE_DIR,
        help="the directory that receives the manifest and the artifacts",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=DEFAULT_INVENTORY,
        help="the requirement-linked check inventory",
    )
    parser.add_argument(
        "--live-muse",
        action="store_true",
        help="incorporate a parent-owned live walkthrough into AT15 and AT19",
    )
    parser.add_argument(
        "--live-evidence",
        type=Path,
        default=None,
        help="the demo-walkthrough.json produced by the bounded live walkthrough",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print the summary only",
    )
    return parser.parse_args(argv)


def acquire_run_lock(evidence_dir: Path):
    """Hold an exclusive lock so two runners cannot rewrite the same artifacts."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    handle = (evidence_dir / ".run.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def main(argv: list[str] | None = None) -> int:
    """Run the acceptance checks and write the manifest of the run."""
    args = parse_args(argv)
    mode = "all" if args.all else "deterministic"
    inventory = load_inventory(args.inventory)
    families = selected_families(inventory, mode=mode)
    evidence_dir = Path(args.evidence_dir).resolve()
    run_lock = acquire_run_lock(evidence_dir)
    if run_lock is None:
        print(
            f"acceptance evidence directory is already being written: {evidence_dir}",
            file=sys.stderr,
        )
        return 2
    artifacts = evidence_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    started = datetime.now(UTC)
    versions = run_versions()
    recorder = EvidenceRecorder(
        evidence_dir,
        run_id=f"run_{mode}_{started.strftime('%Y%m%dT%H%M%S')}",
        mode=mode,
        started_at=started,
        build_hash_value=build_hash(REPO_ROOT),
        tree_hash_value=hash_tree(REPO_ROOT),
        fixture_version=str(inventory.get("fixture_version", "")),
        database_schema_revision=str(inventory.get("database_schema_revision", "")),
        source_snapshots=versions["source_snapshots"],
        model=versions["model"],
        prompt_versions=versions["prompt_versions"],
        schema_versions=versions["schema_versions"],
        rule_versions=versions["rule_versions"],
        actors=versions["actors"],
        environment={
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "fictional_demo": "true",
            "mode": mode,
        },
    )

    outcomes: dict[str, str] = {}
    reasons: dict[str, str] = {}
    failures: list[str] = []
    artifact_hashes: dict[str, str] = {}
    for family in families:
        name = family["name"]
        paths = list(family.get("paths") or [])
        if not paths:
            failures.append(f"the family {name} declares no path")
            continue
        missing = [path for path in paths if not (REPO_ROOT / path).exists()]
        if missing:
            failures.append(
                f"the family {name} has no test directory: {', '.join(missing)}"
            )
            continue
        result = run_family(name, paths, artifacts)
        outcomes.update(result.outcomes)
        recorder.record_command(
            command=f"python -m pytest -q {' '.join(PYTEST_WORKERS + paths)}",
            exit_code=result.exit_code,
            collected=result.collected,
            passed=result.passed,
            failed=result.failed,
            skipped=result.skipped,
            duration_seconds=result.duration_seconds,
        )
        if result.junit_path is not None and result.junit_path.is_file():
            reference = recorder.record_artifact(
                result.junit_path, name=f"{name}.junit.xml", kind="report"
            )
            artifact_hashes[name] = reference.sha256
        log_path = artifacts / f"{name}.log"
        if log_path.is_file():
            recorder.record_artifact(log_path, name=f"{name}.log", kind="log")
        if result.collected == 0:
            failures.append(f"the family {name} collected no test")
            recorder.record_failure(f"the family {name} collected no test")
        elif result.failed:
            failures.append(
                f"the family {name} failed: {result.failed} failing test(s)"
            )
        if result.collect_exit_code != 0:
            failures.append(
                f"the family {name} could not be collected cleanly: "
                f"exit {result.collect_exit_code}"
            )
        if result.exit_code != 0 and not result.failed:
            # pytest failed without a failing test case in the report, e.g. an
            # internal or session-finalization error; that still fails the run.
            failures.append(
                f"the family {name} exited {result.exit_code} without a failing test"
            )
        not_run = [node for node in result.nodes if node not in result.outcomes]
        if not_run:
            failures.append(
                f"the family {name} collected {len(not_run)} test(s) that reported no outcome, "
                f"first {not_run[0]}"
            )
        if not args.quiet:
            print(
                f"  {name:<14} exit={result.exit_code} "
                f"collected={result.collected} passed={result.passed} "
                f"failed={result.failed} skipped={result.skipped}",
                flush=True,
            )

    report = evaluator_report()
    live_executed = False
    if args.live_muse:
        live_path = (
            Path(args.live_evidence).resolve()
            if args.live_evidence is not None
            else evidence_dir / "demo-walkthrough.json"
        )
        live_executed, live_payload, live_failure = read_live_evidence(live_path)
        if live_path.is_file():
            copy = artifacts / "live-walkthrough.json"
            if live_path != copy:
                shutil.copyfile(live_path, copy)
            recorder.record_artifact(copy, name=copy.name, kind="live-model-run")
        if not live_executed:
            failure = live_failure or "the requested live provider run did not succeed"
            recorder.record_failure(failure)
            failures.append(failure)
        elif not args.quiet:
            run = live_payload["model_run"]
            print(
                "  live Muse     "
                f"run={run.get('run_id')} response={run.get('response_id')} succeeded",
                flush=True,
            )

    checks = build_checks(
        inventory,
        outcomes,
        reasons,
        report,
        live_executed=live_executed,
        artifact_hashes=artifact_hashes,
    )
    for check in checks:
        recorder.record_check(check)

    for metric in baseline_metrics():
        recorder.record_metric(metric)
    for metric in observed_metrics(report):
        recorder.record_metric(metric)
    for metric in business_metrics(report):
        recorder.record_metric(metric)

    if report:
        source = Path(os.environ.get(EVALUATOR_REPORT_ENV, str(EVALUATOR_REPORT_DEFAULT)))
        if source.is_file():
            copy = artifacts / "evaluator_outcomes.json"
            copy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            recorder.record_artifact(copy, name="evaluator_outcomes.json", kind="report")
    manifest_path = recorder.finalize()

    counts = {"passed": 0, "failed": 0, "blocked": 0}
    for check in checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    acceptance = [check for check in checks if check.kind == CHECK_KIND_ACCEPTANCE]
    supplementary = [check for check in checks if check.kind == CHECK_KIND_SUPPLEMENTARY]
    scenarios = [check for check in checks if check.kind == CHECK_KIND_SCENARIO]
    print("")
    print(f"acceptance checks:   {len(acceptance)}")
    print(f"supplementary checks:{len(supplementary)}")
    print(f"controlled scenarios:{len(scenarios)}")
    print(
        "status: "
        f"passed={counts.get('passed', 0)} "
        f"failed={counts.get('failed', 0)} "
        f"blocked={counts.get('blocked', 0)}"
    )
    for check in checks:
        if check.status == CHECK_STATUS_PASSED:
            continue
        print(f"  {check.status:<8} {check.check_id}: {check.failure}")
    try:
        printed = manifest_path.relative_to(REPO_ROOT)
    except ValueError:
        printed = manifest_path
    print(f"manifest: {printed}")

    failed_checks = [check for check in checks if check.status == CHECK_STATUS_FAILED]
    if failed_checks or failures:
        for failure in failures:
            print(f"  failure: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
