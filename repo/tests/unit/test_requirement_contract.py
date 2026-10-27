"""Contract tests for the committed requirement register."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "config" / "requirements.json"
COVERAGE_SCRIPT = REPO_ROOT / "scripts" / "check_requirement_coverage.py"

EXPECTED_REQUIREMENT_COUNT = 57
EXPECTED_ACCEPTANCE_TESTS = 20
EXPECTED_SUPPLEMENTARY_CHECKS = 8
EXPECTED_SCENARIOS = 11


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_requirement_count_and_distinctness(contract: dict) -> None:
    requirement_ids = [entry["requirement_id"] for entry in contract["requirements"]]
    assert len(requirement_ids) == EXPECTED_REQUIREMENT_COUNT
    assert len(set(requirement_ids)) == EXPECTED_REQUIREMENT_COUNT


def test_acceptance_and_supplementary_check_inventory(contract: dict) -> None:
    acceptance_ids = [entry["test_id"] for entry in contract["acceptance_tests"]]
    supplementary_ids = [entry["check_id"] for entry in contract["supplementary_checks"]]
    scenario_ids = [entry["scenario_id"] for entry in contract["scenarios"]]

    assert len(acceptance_ids) == EXPECTED_ACCEPTANCE_TESTS
    assert len(set(acceptance_ids)) == EXPECTED_ACCEPTANCE_TESTS
    assert acceptance_ids == [f"AT{index:02d}" for index in range(1, EXPECTED_ACCEPTANCE_TESTS + 1)]

    assert len(supplementary_ids) == EXPECTED_SUPPLEMENTARY_CHECKS
    assert len(set(supplementary_ids)) == EXPECTED_SUPPLEMENTARY_CHECKS
    assert supplementary_ids == [
        f"VC{index:02d}" for index in range(1, EXPECTED_SUPPLEMENTARY_CHECKS + 1)
    ]

    assert len(scenario_ids) == EXPECTED_SCENARIOS
    assert len(set(scenario_ids)) == EXPECTED_SCENARIOS
    assert scenario_ids == [f"D{index:02d}" for index in range(1, EXPECTED_SCENARIOS + 1)]


def test_every_requirement_maps_to_a_known_check(contract: dict) -> None:
    known_checks = {entry["test_id"] for entry in contract["acceptance_tests"]}
    known_checks |= {entry["check_id"] for entry in contract["supplementary_checks"]}

    for entry in contract["requirements"]:
        checks = list(entry["acceptance_test_ids"]) + list(entry["supplementary_check_ids"])
        assert checks, f"{entry['requirement_id']} has no planned check"
        assert set(checks) <= known_checks, f"{entry['requirement_id']} references an unknown check"


def test_contract_records_no_source_paths_or_claims(contract: dict) -> None:
    serialized = json.dumps(contract)
    assert "intake/" not in serialized
    assert "ACME_MDM_Build_Package" not in serialized
    assert "requirements_register" not in serialized
    for entry in contract["requirements"]:
        assert set(entry) == {
            "requirement_id",
            "title",
            "area",
            "acceptance_test_ids",
            "supplementary_check_ids",
        }


def test_coverage_script_planning_only_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(COVERAGE_SCRIPT), "--planning-only"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "requirement coverage check OK" in result.stdout
    assert "57 distinct identifiers" in result.stdout


def test_coverage_script_accepts_two_letter_requirement_prefixes() -> None:
    namespace = runpy.run_path(str(COVERAGE_SCRIPT), run_name="coverage_module")
    marker = namespace["REQUIRES_MARKER"]
    match = marker.match("# REQUIRES: AI-01, UX-04")
    assert match is not None
    assert match.group("ids") == "AI-01, UX-04"


def test_coverage_script_rejects_a_duplicated_identifier(tmp_path: Path) -> None:
    broken = tmp_path / "requirements.json"
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["requirements"].append(dict(contract["requirements"][0]))
    broken.write_text(json.dumps(contract), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(COVERAGE_SCRIPT), "--planning-only", "--contract", str(broken)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 1
    assert "duplicate requirement identifier" in result.stderr
