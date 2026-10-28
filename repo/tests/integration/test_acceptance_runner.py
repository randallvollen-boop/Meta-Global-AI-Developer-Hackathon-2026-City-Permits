"""The acceptance runner and the evidence it writes.

The runner keeps the exit code of every child, refuses an empty or a fully
skipped collection, blocks the checks that need a live provider run and
writes a manifest that names the build, the versions and the outcomes.
"""

from __future__ import annotations

import fcntl
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "scripts" / "run_acceptance.py"
SAMPLE_DIRECTORY = REPO_ROOT / "var" / "runner_acceptance"


def load_runner():
    """Return the acceptance runner as a module."""
    spec = importlib.util.spec_from_file_location("run_acceptance_under_test", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def sample_family() -> Path:
    """Create a small family of tests inside the repository."""
    directory = SAMPLE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "test_sample_pass.py").write_text(
        "def test_the_sample_passes() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (directory / "test_sample_skip.py").write_text(
        "import pytest\n"
        "\n"
        "\n"
        "@pytest.mark.skip(reason=\"the sample check is not implemented yet\")\n"
        "def test_the_sample_is_skipped() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


def write_inventory(path: Path, checks: list[dict], families: dict) -> Path:
    """Write a small inventory for the runner."""
    payload = {
        "inventory_version": "1",
        "scope": "acme_city",
        "fictional_demo": True,
        "fixture_version": "2026.10.26-1",
        "database_schema_revision": "0001",
        "families": families,
        "requirements": [
            {
                "requirement_id": "EVAL-03",
                "title": "Reproducible evidence",
                "area": "evaluation and evidence",
                "implementation_symbols": [
                    "src/acme_city/evidence/manifest.py:EvidenceRecorder.finalize"
                ],
                "check_ids": [check["check_id"] for check in checks],
                "node_ids": [
                    node for check in checks for node in check.get("node_ids", [])
                ],
            }
        ],
        "checks": checks,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_a_check_that_passed_is_reported_as_passed() -> None:
    runner = load_runner()
    check = {"check_id": "AT01", "node_ids": ["tests/unit/test_config.py::test_one"]}
    status, failure = runner.status_for(
        check,
        {"tests/unit/test_config.py::test_one": "passed"},
        live_executed=False,
        reasons={},
    )
    assert status == "passed"
    assert failure == ""


def test_a_check_whose_node_failed_is_reported_as_failed() -> None:
    runner = load_runner()
    check = {"check_id": "AT01", "node_ids": ["tests/unit/test_config.py::test_one"]}
    status, failure = runner.status_for(
        check,
        {"tests/unit/test_config.py::test_one": "failed"},
        live_executed=False,
        reasons={},
    )
    assert status == "failed"
    assert "test_one" in failure


def test_a_skipped_check_is_never_reported_as_passed() -> None:
    runner = load_runner()
    check = {"check_id": "AT01", "node_ids": ["tests/unit/test_config.py::test_one"]}
    status, failure = runner.status_for(
        check,
        {"tests/unit/test_config.py::test_one": "skipped"},
        live_executed=False,
        reasons={"tests/unit/test_config.py::test_one": "the sample is not implemented"},
    )
    assert status == "blocked"
    assert "skipped" in failure


def test_a_live_check_is_blocked_in_the_deterministic_mode() -> None:
    runner = load_runner()
    check = {
        "check_id": "AT15",
        "node_ids": ["tests/acceptance/test_at15.py::test_a"],
        "live_required": True,
    }
    status, failure = runner.status_for(
        check,
        {"tests/acceptance/test_at15.py::test_a": "passed"},
        live_executed=False,
        reasons={},
    )
    assert status == "blocked"
    assert "live" in failure

    status, _failure = runner.status_for(
        check,
        {"tests/acceptance/test_at15.py::test_a": "passed"},
        live_executed=True,
        reasons={},
    )
    assert status == "passed"


def test_a_check_without_a_node_is_blocked_when_it_is_pending() -> None:
    runner = load_runner()
    status, failure = runner.status_for(
        {"check_id": "VC03", "node_ids": [], "pending": True},
        {},
        live_executed=False,
        reasons={},
    )
    assert status == "blocked"
    assert "node" in failure

    status, _failure = runner.status_for(
        {"check_id": "AT01", "node_ids": []},
        {},
        live_executed=False,
        reasons={},
    )
    assert status == "failed"


def test_the_runner_writes_a_manifest_and_keeps_the_child_exit_code(
    tmp_path: Path, sample_family: Path
) -> None:
    checks = [
        {
            "check_id": "AT01",
            "kind": "acceptance",
            "title": "the sample passes",
            "expected": "the sample passes",
            "node_ids": ["var/runner_acceptance/test_sample_pass.py::test_the_sample_passes"],
            "evidence_refs": ["sample"],
            "live_required": False,
            "pending": False,
        },
        {
            "check_id": "AT02",
            "kind": "acceptance",
            "title": "the sample is skipped",
            "expected": "the sample is skipped",
            "node_ids": [
                "var/runner_acceptance/test_sample_skip.py::test_the_sample_is_skipped"
            ],
            "evidence_refs": ["sample"],
            "live_required": False,
            "pending": False,
        },
    ]
    families = {"sample": {"paths": ["var/runner_acceptance"], "mode": "deterministic"}}
    inventory = write_inventory(tmp_path / "inventory.json", checks, families)
    evidence = tmp_path / "evidence"

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER_PATH),
            "--deterministic",
            "--inventory",
            str(inventory),
            "--evidence-dir",
            str(evidence),
            "--quiet",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "deterministic"
    assert manifest["build_hash"] and manifest["tree_hash"]
    assert manifest["fixture_version"] == "2026.10.26-1"
    assert manifest["commands"][0]["exit_code"] == 0
    assert manifest["commands"][0]["collected"] == 2
    statuses = {check["check_id"]: check["status"] for check in manifest["checks"]}
    assert statuses == {"AT01": "passed", "AT02": "blocked"}
    assert manifest["artifacts"], "the manifest names no artifact"
    for artifact in manifest["artifacts"]:
        target = evidence / "artifacts" / artifact["name"]
        assert target.is_file()
        assert len(artifact["sha256"]) == 64

    verified = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "verify_evidence.py"), str(evidence)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # The verifier requires the full inventory of twenty, eight and eleven
    # checks, so a small run is reported as incomplete rather than as valid.
    assert verified.returncode == 1
    assert "verification FAILED" in verified.stderr


def test_the_runner_fails_when_a_child_fails(tmp_path: Path, sample_family: Path) -> None:
    (sample_family / "test_sample_fail.py").write_text(
        "def test_the_sample_fails() -> None:\n"
        "    assert False, \"a fictional failing sample\"\n",
        encoding="utf-8",
    )
    try:
        checks = [
            {
                "check_id": "AT01",
                "kind": "acceptance",
                "title": "the sample fails",
                "expected": "the sample passes",
                "node_ids": [
                    "var/runner_acceptance/test_sample_fail.py::test_the_sample_fails"
                ],
                "evidence_refs": ["sample"],
                "live_required": False,
                "pending": False,
            }
        ]
        families = {
            "sample": {"paths": ["var/runner_acceptance"], "mode": "deterministic"}
        }
        inventory = write_inventory(tmp_path / "inventory.json", checks, families)
        evidence = tmp_path / "evidence"

        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER_PATH),
                "--deterministic",
                "--inventory",
                str(inventory),
                "--evidence-dir",
                str(evidence),
                "--quiet",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 1
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["commands"][0]["exit_code"] == 1
        assert manifest["commands"][0]["failed"] == 1
        assert manifest["checks"][0]["status"] == "failed"
        assert manifest["failures"]
    finally:
        (sample_family / "test_sample_fail.py").unlink()


def test_the_runner_rejects_an_empty_family(tmp_path: Path) -> None:
    empty = REPO_ROOT / "var" / "runner_empty"
    empty.mkdir(parents=True, exist_ok=True)
    try:
        checks = [
            {
                "check_id": "AT01",
                "kind": "acceptance",
                "title": "an empty family",
                "expected": "something",
                "node_ids": [],
                "evidence_refs": [],
                "live_required": False,
                "pending": True,
            }
        ]
        families = {"empty": {"paths": ["var/runner_empty"], "mode": "deterministic"}}
        inventory = write_inventory(tmp_path / "inventory.json", checks, families)
        evidence = tmp_path / "evidence"
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER_PATH),
                "--deterministic",
                "--inventory",
                str(inventory),
                "--evidence-dir",
                str(evidence),
                "--quiet",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 1
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["commands"][0]["exit_code"] == 5
        assert any(
            "collected no test" in failure for failure in manifest["failures"]
        )
    finally:
        empty.rmdir()

def test_the_deterministic_mode_leaves_the_browser_family_alone() -> None:
    """The browser family needs a running service and is not deterministic."""
    runner = load_runner()
    inventory = {
        "families": {
            "unit": {"paths": ["tests/unit"], "mode": "deterministic"},
            "browser": {"paths": ["tests/browser"], "mode": "browser"},
        }
    }
    deterministic = [
        entry["name"] for entry in runner.selected_families(inventory, mode="deterministic")
    ]
    every = [entry["name"] for entry in runner.selected_families(inventory, mode="all")]
    assert deterministic == ["unit"]
    assert every == ["unit", "browser"]


def test_an_evidence_directory_allows_only_one_runner(tmp_path: Path) -> None:
    runner = load_runner()
    evidence = tmp_path / "evidence"
    first = runner.acquire_run_lock(evidence)
    assert first is not None
    try:
        assert runner.acquire_run_lock(evidence) is None
    finally:
        first.close()
    second = runner.acquire_run_lock(evidence)
    assert second is not None
    second.close()


def test_the_verifier_refuses_an_active_run(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    lock = (evidence / ".run.lock").open("a+", encoding="utf-8")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "verify_evidence.py"),
                str(evidence),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 2
        assert "still being written" in completed.stderr
    finally:
        lock.close()


def test_live_evidence_requires_a_successful_live_provider_response(tmp_path: Path) -> None:
    runner = load_runner()
    failed = tmp_path / "failed.json"
    failed.write_text(
        json.dumps(
            {
                "mode": "live",
                "status": "failed",
                "model_run": {
                    "mode": "live",
                    "status": "failed",
                    "response_id": "resp_fictional_failed",
                    "response_status": "incomplete",
                },
            }
        ),
        encoding="utf-8",
    )
    succeeded, _payload, reason = runner.read_live_evidence(failed)
    assert succeeded is False
    assert "did not succeed" in reason

    live = tmp_path / "live.json"
    live.write_text(
        json.dumps(
            {
                "mode": "live",
                "status": "passed",
                "model_run": {
                    "mode": "live",
                    "status": "succeeded",
                    "response_id": "resp_fictional_success",
                    "response_status": "completed",
                },
            }
        ),
        encoding="utf-8",
    )
    succeeded, _payload, reason = runner.read_live_evidence(live)
    assert succeeded is True
    assert reason == ""

    replay = tmp_path / "replay.json"
    replay.write_text(
        json.dumps(
            {
                "mode": "replay",
                "status": "passed",
                "model_run": {
                    "mode": "replay",
                    "status": "succeeded",
                    "response_id": "resp_fictional_replay",
                },
            }
        ),
        encoding="utf-8",
    )
    succeeded, _payload, reason = runner.read_live_evidence(replay)
    assert succeeded is False
    assert "cannot satisfy" in reason


def test_a_live_check_whose_deterministic_node_failed_is_failed_not_blocked() -> None:
    runner = load_runner()
    check = {
        "check_id": "AT15",
        "node_ids": ["tests/acceptance/test_at15.py::test_a"],
        "live_required": True,
    }
    status, failure = runner.status_for(
        check,
        {"tests/acceptance/test_at15.py::test_a": "failed"},
        live_executed=False,
        reasons={},
    )
    assert status == "failed"
    assert "test_a" in failure

    status, failure = runner.status_for(
        check, {}, live_executed=False, reasons={}
    )
    assert status == "failed"
    assert "did not run" in failure


def test_the_runner_fails_when_pytest_exits_nonzero_without_a_failing_test(
    tmp_path: Path, sample_family: Path
) -> None:
    # Every test case passes, but the session ends with an error, so pytest
    # exits nonzero.  The run must still fail.
    (sample_family / "conftest.py").write_text(
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    raise RuntimeError(\"a fictional session-finalization error\")\n",
        encoding="utf-8",
    )
    checks = [
        {
            "check_id": "AT01",
            "kind": "acceptance",
            "title": "the sample passes",
            "expected": "the sample passes",
            "node_ids": ["var/runner_acceptance/test_sample_pass.py::test_the_sample_passes"],
            "evidence_refs": ["sample"],
            "live_required": False,
            "pending": False,
        },
    ]
    families = {"sample": {"paths": ["var/runner_acceptance"], "mode": "deterministic"}}
    inventory = write_inventory(tmp_path / "inventory.json", checks, families)
    evidence = tmp_path / "evidence"

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER_PATH),
            "--deterministic",
            "--inventory",
            str(inventory),
            "--evidence-dir",
            str(evidence),
            "--quiet",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "exited" in completed.stderr or "could not be collected" in completed.stderr
    log = evidence / "artifacts" / "sample.log"
    assert log.is_file()
    assert "session-finalization" in log.read_text(encoding="utf-8")
