"""The data inputs of the controlled scenarios are unchanged.

``data/protected_fixture_hashes.json`` records the sha256 of every data and
fixture input the D01-D11 scenarios, the DF-1/DF-2 fence rules and the
acceptance tests read: the files under ``fixtures/`` (the seeded population,
the source variations, the evaluator truth, the town, the documents and the
replay cassettes), ``config/rules_and_fees.json`` with the rule texts, and the
seed subtrees of ``config/demo.json``, hashed per key so a new top-level key
does not trip the guard.  Test modules are not hashed.

A lane never edits the recorded hashes to make this pass.  A deliberate,
reviewed change of a protected input is recorded by running this module as a
script, which rewrites the hashes of the inputs already listed.
"""
# REQUIRES: D01, D02, D03, D04, D05, D06, D07, D08, D09, D10, D11
# The data inputs of the controlled scenarios, the rules and the replays keep the
# bytes the outcomes were accepted against.

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
HASHES = Path(__file__).resolve().parent / "data" / "protected_fixture_hashes.json"
DEMO_JSON = "config/demo.json"


def _recorded() -> dict[str, Any]:
    return json.loads(HASHES.read_text(encoding="utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _key_hash(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _sha256(canonical.encode("utf-8"))


def observed_hashes(root: Path, recorded: dict[str, Any]) -> dict[str, Any]:
    """Return the hashes of the protected inputs under ``root``.

    The protected inputs are the ones ``recorded`` lists.  A missing file or a
    missing ``demo.json`` key is reported as ``None``.
    """
    files: dict[str, str | None] = {}
    for relative in recorded["files"]:
        path = root / relative
        files[relative] = _sha256(path.read_bytes()) if path.is_file() else None
    demo = json.loads((root / DEMO_JSON).read_text(encoding="utf-8"))
    keys = {
        key: (_key_hash(demo[key]) if key in demo else None)
        for key in recorded["demo_json_keys"]
    }
    return {"files": files, "demo_json_keys": keys}


def _changed(observed: dict[str, Any], recorded: dict[str, Any]) -> list[str]:
    changed = [
        path for path, digest in recorded["files"].items() if observed["files"][path] != digest
    ]
    changed += [
        f"{DEMO_JSON}#{key}"
        for key, digest in recorded["demo_json_keys"].items()
        if observed["demo_json_keys"][key] != digest
    ]
    return changed


def _scratch_copy(target: Path, recorded: dict[str, Any]) -> Path:
    for relative in [*recorded["files"], DEMO_JSON]:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, destination)
    return target


def test_the_protected_inputs_are_unchanged() -> None:
    recorded = _recorded()
    assert recorded["files"] and recorded["demo_json_keys"]
    assert _changed(observed_hashes(REPO, recorded), recorded) == []


def test_the_guard_covers_the_scenario_rule_and_replay_inputs() -> None:
    recorded = _recorded()
    files = set(recorded["files"])
    assert {
        "fixtures/base_population.json",
        "fixtures/source_variations.json",
        "fixtures/evaluator_truth.json",
        "config/rules_and_fees.json",
    } <= files
    assert any(path.startswith("fixtures/replay/") for path in files)
    assert any(path.startswith("fixtures/documents/") for path in files)
    # Every fixture file present now is protected.
    on_disk = {
        path.relative_to(REPO).as_posix()
        for path in (REPO / "fixtures").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert on_disk <= files, sorted(on_disk - files)
    assert {"scenarios", "reason_codes", "fixture_version"} <= set(recorded["demo_json_keys"])
    # The rule texts of the fence rules are among the hashed bytes.
    rules = json.loads((REPO / "config/rules_and_fees.json").read_text(encoding="utf-8"))
    assert {"DF-1", "DF-2"} <= {rule["rule_id"] for rule in rules["rules"]}


@pytest.mark.parametrize(
    "relative",
    [
        "fixtures/base_population.json",
        "fixtures/replay/extraction-success.json",
        "fixtures/documents/SYN-APP-001-application-v1.txt",
        "config/rules_and_fees.json",
    ],
)
def test_one_changed_byte_in_a_scratch_copy_trips_the_guard(tmp_path: Path, relative: str) -> None:
    recorded = _recorded()
    scratch = _scratch_copy(tmp_path, recorded)
    assert _changed(observed_hashes(scratch, recorded), recorded) == []
    path = scratch / relative
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))
    assert _changed(observed_hashes(scratch, recorded), recorded) == [relative]


def test_a_demo_json_seed_key_is_hashed_and_a_new_key_is_not(tmp_path: Path) -> None:
    recorded = _recorded()
    scratch = _scratch_copy(tmp_path, recorded)
    demo_path = scratch / DEMO_JSON
    demo = json.loads(demo_path.read_text(encoding="utf-8"))
    demo["a_new_lane_key"] = {"anything": True}
    demo_path.write_text(json.dumps(demo, indent=4), encoding="utf-8")
    assert _changed(observed_hashes(scratch, recorded), recorded) == []
    demo["scenarios"][0]["title"] += "."
    demo_path.write_text(json.dumps(demo, indent=4), encoding="utf-8")
    assert _changed(observed_hashes(scratch, recorded), recorded) == [f"{DEMO_JSON}#scenarios"]


def _rewrite() -> None:
    """Record the current hashes of the inputs already listed."""
    recorded = _recorded()
    observed = observed_hashes(REPO, recorded)
    recorded.update(observed)
    HASHES.write_text(json.dumps(recorded, indent=2, sort_keys=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    _rewrite()
    sys.exit(0)
