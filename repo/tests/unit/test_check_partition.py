"""The full check run executes every test directory exactly once."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_acceptance import load_inventory, selected_families  # noqa: E402
from run_all_checks import INVENTORY_PATH, pytest_only_paths  # noqa: E402


def test_pytest_step_and_acceptance_step_partition_the_test_directories() -> None:
    acceptance = {
        path
        for family in selected_families(load_inventory(INVENTORY_PATH), mode="deterministic")
        for path in family.get("paths") or []
    }
    plain = set(pytest_only_paths())
    every = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "tests").iterdir()
        if path.is_dir() and path.name != "__pycache__"
    }
    assert plain, "the pytest step must run the directories the acceptance step leaves out"
    assert not plain & acceptance, "a test directory would run twice"
    assert plain | acceptance >= every, "a test directory would never run"
