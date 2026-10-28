"""The full check run executes every test directory and root test file exactly once."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_acceptance import load_inventory, selected_families  # noqa: E402
from run_all_checks import INVENTORY_PATH, pytest_only_paths  # noqa: E402


def acceptance_paths() -> list[str]:
    return [
        Path(path).as_posix().rstrip("/")
        for family in selected_families(load_inventory(INVENTORY_PATH), mode="deterministic")
        for path in family.get("paths") or []
    ]


def test_family_paths_are_unique_top_level_test_directories() -> None:
    families = load_inventory(INVENTORY_PATH)["families"]
    every = [
        Path(path).as_posix().rstrip("/")
        for definition in families.values()
        for path in definition.get("paths") or []
    ]
    duplicated = [path for path, count in Counter(every).items() if count > 1]
    assert not duplicated, f"a test path is declared by more than one family: {duplicated}"
    for path in every:
        parts = Path(path).parts
        assert len(parts) == 2 and parts[0] == "tests", (
            f"{path} is not a top-level test directory; nested or file paths "
            "would break the exactly-once partition"
        )
        assert (REPO_ROOT / path).is_dir(), f"{path} does not exist"


def test_pytest_step_and_acceptance_step_partition_the_test_tree() -> None:
    acceptance = set(acceptance_paths())
    plain = set(pytest_only_paths())
    every = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "tests").iterdir()
        if (path.is_dir() and path.name != "__pycache__")
        or (path.is_file() and path.name.startswith("test_") and path.suffix == ".py")
    }
    assert plain, "the pytest step must run what the acceptance step leaves out"
    assert not plain & acceptance, "a test path would run twice"
    assert plain | acceptance >= every, "a test path would never run"
